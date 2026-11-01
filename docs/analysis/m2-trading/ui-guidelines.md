# M2-6 scoped UI-guideline verification

The owner explicitly extended this first-round UI work after merged PR127.
Main's documentation-only changes were merged normally; no history was rewritten.
This implements only the M2-6 regions already changed. Four header badges,
the complete overview dashboard and global UX-1 work remain later scope.

Each changed page's explanatory controls are on its title's right, retaining
each complete original PlainText help dialog and keyboard/Escape behavior.
`widgets.button` accepts keyword `role` with default secondary. The trade
reconcile action is primary; the empty-strategy CTA is the overview's only
primary. Stop/cancel/flatten are danger controls. Five actual UI controls reach
the existing confirmation dialog with Cancel as default; cancelling sends zero
commands. Confirmed stop/cancel still use the existing command/priority path.
The confirmation captures context, account, environment and book version, and
refuses a changed selection instead of acting on a new book.

Positions retain all12 columns/values but show exactly six by default: product,
quantity, sellable, strategy, exit and protection. The keyboard-operable column
menu remembers optional selections through an injected callback. Runtime
composition owns `trading-presentation-v1.json` using the existing atomic
SettingsStore. It is separate from trading/market settings, and a corrupt future
file is preserved; a failed write restores accepted column choices and reports
failure. Product is mandatory, so a restored empty selection cannot hide it.
The Qt presentation imports no storage or path API. Stock quantities display
exact decimal lots, numeric cells align right, and timestamped quotes render
Taipei time; no financial/domain facts are changed.

Empty positions/orders explain why they are empty and offer a keyboard route
to the strategy page, with no mutation. The overview retains its explicit
first-strategy wizard action and now also shows its reason. No fabricated
position/order placeholder is inserted into the model.

Seven new cases failed on the old source, then passed. An eighth actual-widget
case verifies units/alignment/time without changing underlying facts. The
final new cases include real native Cancel defaults, actual danger colors,
context reentry refusal, a keyboard Return on the native column menu, actual
SettingsStore restart persistence, failed-write rollback, header placement and
empty-state navigation. Existing financial, independent LIVE-intent inventory,
timing, keyboard/wiring and metadata assertions are preserved. Only approved
confirmation interaction and exact presentation pins change separately.

Verification before delivery:

- Affected widget/wiring/architecture batch:93 tests passed in76.042 seconds.
- Final new/original M2-6 and appearance batch:34 tests passed in17.831 seconds.
- Exact catalogue, literal text and architecture/layer/document gates:65 tests
  passed in19.186 seconds after the ten-key fixture was regenerated.
- Ruff, layer and strict trading architecture checks:zero findings.
- All six populated1366×768/1920×1080 trading captures were renewed, showing
  exactly six visible columns, first product column119px for112px text, and
  horizontal scrollbar maximum0. Overview/changed explanation/help captures
  were also renewed and personally inspected.
- Catalogue adds exactly10 literal records2796–2805, total2806 ordered records
  (2805 unique locale keys), no alias changes;
  exact pins and confirmation-aware old tests are a separate baseline commit.
- GitNexus MCP transport was closed, so the same GitNexus CLI was used. A force
  rebuild repaired incremental empty-UID results. Shared theme File impact is
  CRITICAL31 direct; helper button MEDIUM7 direct. Page/formatter/composition
  flows are LOW/MEDIUM; Qt constructors and tests UNKNOWN were confirmed in
  source. Parser candidate/trace caps and degraded FTS remain explicit limits;
  no repair/download or zero-edge safety inference was used.

PR checklist (UI guidelines section10, scoped to this delivery):

- [x] Title/help layout; at most one primary; danger actions confirm with Cancel.
- [x] New styles are only in theme.py; reuse the existing role property.
- [x] Changed empty regions explain the next step and expose an action.
- [x] Both required screenshot sizes; no default position horizontal scrollbar.
- [x] New copy is Chinese; quote timestamps use Taipei; existing date separation
  remains. Global code/time cleanup outside the modified regions is UX-1.
- [x] New controls have accessible names and real keyboard evidence.

Full discovery, both actual `_run_window` starts and remote CI are still root
coordination after the final source/baseline head. Earlier79fc99c startup
measurements do not validate this source. No real login, CA activation, SDK
import, order or background engine was used for these UI captures/tests.

Final4fd1f6e full/startup evidence supersedes the earlier pending stage:3941tests
with zero new failure IDs, actual LOCAL6.075s/fake-SIM3.969s both return0 and clean
research/engine shutdown. The local full suite remains nonzero on reviewed main
host limitations; remote CI is separately required on the pushed PR head. See
[final comparison](final-full-comparison.json), [startup facts](final-startup.json)
and [the final verification section](verification.md#final-source-equivalent-validation).
