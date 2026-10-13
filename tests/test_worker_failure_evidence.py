from pathlib import Path
import hashlib,re,unittest
ROOT=Path(__file__).resolve().parents[1]
class WorkerFailureEvidenceContracts(unittest.TestCase):
    def test_supervisor_guards_are_byte_identical_after_removing_only_diagnostics(self):
        helper=(ROOT/"packaging/acceptance_process.ps1").read_text(encoding="utf-8-sig")
        body="# Windows-only"+helper.split("# Windows-only",1)[1]
        begin=body.index("  $workerFailurePath=")
        end=body.index("  $encoded =",begin)
        original_command="  $command = '$ErrorActionPreference=''Stop''; $global:LASTEXITCODE=0; try { ' + $command + '; $ok=$?; $code=$global:LASTEXITCODE; if ($code -ne 0) { exit $code }; if (-not $ok) { exit 1 }; exit 0 } catch { [Console]::Error.WriteLine(''Acceptance worker failed; see saved evidence''); exit 1 }'\n"
        body=body[:begin]+original_command+body[end:]
        self.assertEqual(hashlib.sha256(body.replace("\n","\r\n").encode()).hexdigest(),"76d2966d05411f73f93f5e48b6d68d0b7a059f867ce336ce729ac503441c6483")
        self.assertIn("$job = New-Object MarkAutoAcceptanceJob($name)",body)
        self.assertIn("[int]$LimitSeconds = 1200",body)
        self.assertIn("-lt 6GB",body)
    def test_prepared_state_and_freshness_guards_are_unchanged(self):
        source=(ROOT/"packaging/prepared_host_session.ps1").read_text(encoding="utf-8-sig")
        source=re.sub(r"^[ \t]*\$global:acceptanceDiagnosticPhase='[^']+'\n","",source,flags=re.M)
        begin=source.index("} catch {\n  try { Write-AcceptanceWorkerFailure")
        end=source.index("\nfinally {",begin)
        source=source[:begin]+"} catch { $record.reason='Prepared-host phase preflight, integrity, UI or owned-process assertion failed'; throw }"+source[end:]
        original_bytes=b"\xef\xbb\xbf"+source.replace("\n","\r\n").encode()
        self.assertEqual(hashlib.sha256(original_bytes).hexdigest(),"2b338c9d43e05d38c07a5a7cc2d1d07156939119c3a0e8cd8f9d026ed2c4257f")
        self.assertTrue((ROOT/"packaging/prepared_host_session.ps1").read_bytes().startswith(b"\xef\xbb\xbf"))
    def test_writer_never_serializes_errorrecord_payload(self):
        source=(ROOT/"packaging/acceptance_process.ps1").read_text()
        writer=source.split("# Windows-only",1)[0]
        for forbidden in (".TargetObject",".PositionMessage",".InvocationInfo.Line",".Arguments",".Environment", "ConvertTo-Json"):
            self.assertNotIn(forbidden,writer)
        for required in ("$i -lt 4","$frames.Count -ge 8","16384","256","$bytes.Length -gt 8192",
                         "[IO.FileMode]::CreateNew","$stream.Flush($true)","other_exception","other_function","other_script"):
            self.assertIn(required,writer)
        self.assertNotIn('"message":',writer)
        self.assertNotIn('"trace":',writer)
    def test_encoded_catch_is_self_contained_and_keeps_failure_status(self):
        source=(ROOT/"packaging/acceptance_process.ps1").read_text()
        self.assertIn("$writerDefinition=(Get-Command Write-AcceptanceWorkerFailure",source)
        self.assertIn("$prefix='function Write-AcceptanceWorkerFailure",source)
        self.assertIn("-Source encoded_wrapper -Phase $global:acceptanceDiagnosticPhase",source)
        self.assertIn("diagnostic unavailable; primary failure preserved",source)
        self.assertIn("exit 1",source)
        self.assertIn("if ($code -ne 0) { exit $code }",source)
    def test_primary_record_precedes_owned_cleanup_and_is_separate(self):
        source=(ROOT/"packaging/prepared_host_session.ps1").read_text(encoding="utf-8-sig")
        catch=source.split("} catch {\n  try { Write-AcceptanceWorkerFailure",1)[1]
        self.assertLess(catch.index("-Source prepared_runtime"),catch.index("Close-AcceptanceProcesses"))
        self.assertIn("'worker-failure.json'",catch)
        self.assertIn("'session-results.json'",catch)
    def test_native_diagnostic_controls_and_evidence_are_mandatory_in_ci(self):
        workflow=(ROOT/".github/workflows/windows-desktop.yml").read_text(encoding="utf-8")
        self.assertIn("run: ./packaging/test_worker_failure_evidence.ps1",workflow)
        self.assertIn("path: dist/validation/worker-failure-native",workflow)
        block=workflow.split("name: Preserve bounded worker failure evidence even on failure",1)[1].split("- name:",1)[0]
        self.assertIn("if: always()",block)
        self.assertIn("if-no-files-found: error",block)
    def test_native_fixture_reserves_guid_root_and_refuses_collisions_and_redirects(self):
        fixture=(ROOT/"packaging/test_worker_failure_evidence.ps1").read_text(encoding="utf-8-sig")
        allocator=fixture.split("function New-WorkerFailureFixtureRoot",1)[1].split("function Require-WorkerFixture",1)[0]
        self.assertIn("[guid]::NewGuid().ToString('N')",allocator)
        self.assertIn("$ancestors.Push($inspect)",allocator)
        self.assertIn("$ancestors.Pop()",allocator)
        self.assertLess(allocator.index("Assert-AcceptancePath $runPath -RequireAbsent"),allocator.index("CreateDirectory($runPath)"))
        self.assertNotIn("yyyyMMddTHHmmssZ",fixture)
        for case in ("directory_collision","file_collision","reparse_evidence_root","reparse_evidence_ancestor"):
            self.assertIn("'"+case+"'",fixture)
        self.assertIn("$run=New-WorkerFailureFixtureRoot $EvidenceRoot",fixture)
        self.assertLess(fixture.index("$run=New-WorkerFailureFixtureRoot"),fixture.index("[IO.File]::WriteAllText"))
    def test_synthetic_controls_cover_reviewed_failures(self):
        fixture=(ROOT/"packaging/test_worker_failure_evidence.ps1").read_text(encoding="utf-8-sig")
        for case in ("early","runtime","primary_cleanup","secret_record","preexisting_output","denied_output","partial_exit"):
            self.assertIn("'"+case+"'",fixture)
        self.assertIn("Invoke-AcceptanceSupervisor -ScriptPath $worker",fixture)
        self.assertIn("Confirm-AcceptanceWorker $AcceptanceJob",fixture)
        self.assertIn("cleanup_verified",fixture)
        self.assertIn("remaining_owned",fixture)
        self.assertNotIn("Set-Acl",fixture)
        self.assertNotIn("ExecutionPolicy",fixture)
if __name__=="__main__":unittest.main()
