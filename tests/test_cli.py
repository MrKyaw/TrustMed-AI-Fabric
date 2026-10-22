
from trustmed_fabric.cli import main


def test_cli_seed_and_claims(tmp_path, capsys) -> None:
    db = tmp_path / "cli.db"
    assert main(["--db", str(db), "seed"]) == 0
    assert main(["--db", str(db), "claims"]) == 0
    assert main(["--db", str(db), "policies"]) == 0
    assert main(["--db", str(db), "gaps"]) == 0
    assert main(["--db", str(db), "audit", "verify"]) == 0
    output = capsys.readouterr().out
    assert "ledger_events" in output or "valid" in output


def test_cli_trace_and_evaluate(tmp_path, capsys) -> None:
    db = tmp_path / "cli2.db"
    main(["--db", str(db), "seed"])
    assert main(["--db", str(db), "trace", "ONC-HCP-DA-001"]) == 0
    code = main(["--db", str(db), "evaluate", "ONC-HCP-DA-001", "--market", "US", "--audience", "HCP", "--channel", "WEB"])
    assert code == 0


def test_cli_ask_and_eval(tmp_path, capsys) -> None:
    db = tmp_path / "cli3.db"
    main(["--db", str(db), "seed"])
    assert main(["--db", str(db), "ask", "What progression-free survival result did HORIZON-3 show for Oncravia?", "--market", "US", "--audience", "HCP", "--json"]) == 0
    assert main(["--db", str(db), "eval", "--no-write"]) == (0 if True else 1)
    captured = capsys.readouterr()
    assert "PASS" in captured.out or "passed" in captured.out.lower()


def test_cli_audit_export(tmp_path) -> None:
    db = tmp_path / "cli4.db"
    main(["--db", str(db), "seed"])
    output = tmp_path / "ledger.ndjson"
    assert main(["--db", str(db), "audit", "export", "--output", str(output)]) == 0
    assert output.exists()
    assert output.read_text().count("\n") > 1


def test_cli_publish(tmp_path) -> None:
    db = tmp_path / "cli5.db"
    main(["--db", str(db), "seed"])
    assert main(["--db", str(db), "publish", "ONC-HCP-DA-001", "EXP-WEB-US-ONC-HCP", "https://demo.trustmed.example/cli"]) == 0
