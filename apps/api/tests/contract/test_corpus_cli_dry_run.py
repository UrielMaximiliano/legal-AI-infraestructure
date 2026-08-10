from pathlib import Path

import legal_ai.cli.corpus as corpus_cli
from legal_ai.cli.corpus import main


class _EmptyLookup:
    def __init__(self, session) -> None:
        self.session = session

    async def lookup(self, *, identities, normalized_content_hashes):
        return ()


def test_corpus_cli_dry_run_is_default(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(corpus_cli, "SQLAlchemyCorpusDeduplicationLookup", _EmptyLookup)
    (tmp_path / "one.txt").write_text("ARTÍCULO 1°.- Uno", encoding="utf-8")
    assert main(["ingest", str(tmp_path)]) == 0
    assert '"execution_mode":"DRY_RUN"' in capsys.readouterr().out


def test_corpus_cli_execute_validates_the_path_before_provider_configuration(
    tmp_path: Path, capsys
) -> None:
    missing = tmp_path / "does-not-exist"
    assert main(["ingest", str(missing), "--execute"]) == 2
    output = capsys.readouterr().out
    assert "CORPUS_PATH_INVALID" in output


def test_evaluate_and_probe_commands_are_explicit_opt_in() -> None:
    parser = corpus_cli.build_parser()
    evaluation = parser.parse_args(["evaluate", "--dataset", "dataset.json"])
    probe = parser.parse_args(["probe-embedding", "--timeout", "5"])
    assert evaluation.provider == "fake"
    assert probe.timeout == 5


def test_activate_staged_index_is_dry_run_by_default_and_guarded() -> None:
    parser = corpus_cli.build_parser()
    dry_run = parser.parse_args(
        ["activate-staged-index", "--expected-database", "isolated_test"]
    )
    execute = parser.parse_args(
        [
            "activate-staged-index",
            "--expected-database",
            "isolated_test",
            "--execute",
        ]
    )

    assert dry_run.execute is False
    assert dry_run.generation == 1
    assert dry_run.batch_size == 100
    assert execute.execute is True
