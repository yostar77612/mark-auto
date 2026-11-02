"""A bounded stock job publishes one durable artifact only after complete success."""

from dataclasses import replace
from hashlib import sha256
from time import monotonic

from .codec import dumps, loads
from .stock_research import PRODUCER, StockResearchArtifact, artifact_material, backtest_stock, validate_request
from .research import research_fingerprint
from quantlab.trading.domain.strategy import ResearchEvidence
from quantlab.trading.domain.validation import DomainError

MAX_SECONDS = 15 * 60
EVENT_KIND = 'official_stock_training_completed'


class StockResearchService:
    def __init__(self, sync, journal, clock, calendar, profile, *, timer=monotonic, profile_reader=None):
        self.sync, self.journal, self.clock = sync, journal, clock
        self.calendar, self.profile, self.timer = calendar, profile, timer
        self.profile_reader = profile_reader

    def run(self, strategy, spec, start, end, fees, treatment, *, partition='TRAINING', cancelled=lambda: False, max_seconds=MAX_SECONDS):
        validate_request(strategy, spec, treatment, fees, partition)
        if type(max_seconds) not in (int, float) or not 0 < max_seconds <= MAX_SECONDS:
            raise DomainError('validation_failed', 'bounded stock job deadline required')
        started = self.timer()
        heartbeat_at = started

        def checkpoint():
            nonlocal heartbeat_at
            now = self.timer()
            if cancelled():
                raise DomainError('research_cancelled', 'stock training cancelled without evidence')
            if now - started >= max_seconds:
                raise DomainError('research_timeout', 'stock training deadline exceeded')
            if now - heartbeat_at >= 5:
                self.journal.heartbeat(self.clock.now())
                heartbeat_at = now

        checkpoint()
        inputs = self.sync.research_inputs(spec.instrument_id, start, end, self.calendar, fees)
        if any(self.calendar.day_session(bar.trade_date).closes_at >= self.clock.now() for bar in inputs.batch.bars):
            raise DomainError('official_stock_coverage_missing', 'only completed training observations may enter research')
        prior = self.journal.replay()
        checkpoint()
        result = backtest_stock(strategy, spec, self.calendar, inputs, profile=self.profile, checkpoint=checkpoint)
        metadata = (
            *inputs.evidence(),
            ('stock_kind', treatment.stock_kind),
            ('day_trade', str(treatment.day_trade)),
            ('pnl_basis', 'raw-price-pnl; unmodeled entitlement crossings refused'),
            ('sizing', 'one instrument lot within raw-price entry cash allocation'),
            ('calendar_digest', sha256(dumps(self.calendar).encode()).hexdigest()),
        )
        clean_strategy = replace(strategy, evidence='', evidence_hash='', research_blob='')
        material = artifact_material(result, metadata, inputs.batch.events, fees, treatment, clean_strategy, spec, self.calendar, self.profile)
        result_hash = sha256(dumps(material).encode()).hexdigest()
        strategy_hash = strategy.definition.fingerprint if strategy.definition else sha256(dumps((strategy.form, strategy.policy)).encode()).hexdigest()
        evidence = ResearchEvidence('BACKTEST', strategy_hash, result.dataset_id, result.producer, self.clock.now(), 'TRAINING', result_hash)
        artifact = StockResearchArtifact(evidence, result, fees, treatment, metadata, inputs.batch.events, clean_strategy, spec, self.calendar, self.profile)
        payload = dumps(artifact)
        checkpoint()
        if self.profile_reader is not None and self.profile_reader() != self.profile:
            raise DomainError('source_invalid_evidence', 'stock source changed before publication')
        self.journal.append(EVENT_KIND, payload, self.clock.now(), expected_sequence=len(prior))
        return artifact

    def history(self):
        artifacts = []
        for event in self.journal.replay():
            if event.kind != EVENT_KIND:
                raise DomainError('source_invalid_evidence', 'unexpected stock evidence journal event')
            artifact = loads(event.payload)
            if not isinstance(artifact, StockResearchArtifact):
                raise DomainError('source_invalid_evidence', 'stock artifact required')
            material = artifact_material(
                artifact.result,
                artifact.metadata,
                artifact.events,
                artifact.fees,
                artifact.treatment,
                artifact.strategy,
                artifact.instrument,
                artifact.calendar,
                artifact.profile,
            )
            expected = sha256(dumps(material).encode()).hexdigest()
            strategy = artifact.strategy
            strategy_hash = strategy.definition.fingerprint if strategy.definition else sha256(dumps((strategy.form, strategy.policy)).encode()).hexdigest()
            fingerprint = research_fingerprint(strategy, artifact.instrument, artifact.calendar, artifact.fees, artifact.result.dataset_id, artifact.profile)
            if (
                expected != artifact.evidence.result_hash
                or artifact.result.partition != 'TRAINING'
                or artifact.evidence.partition != 'TRAINING'
                or artifact.evidence.stage != 'BACKTEST'
                or artifact.evidence.dataset_id != artifact.result.dataset_id
                or artifact.evidence.producer != PRODUCER
                or artifact.result.producer != PRODUCER
                or artifact.evidence.strategy_fingerprint != strategy_hash
                or artifact.result.fingerprint != fingerprint
            ):
                raise DomainError('source_invalid_evidence', 'stock artifact integrity mismatch')
            artifacts.append(artifact)
        return tuple(artifacts)
