"""NBAClient.designated_teams — no network: _fetch_df is replaced with a fixed frame."""

import pandas as pd
import pytest

from nba.client import NBAClient, NBAClientError

DAL, DET = 1610612742, 1610612765


def _client(tmp_path, monkeypatch, summary):
    client = NBAClient(tmp_path)
    monkeypatch.setattr(client, "_fetch_df", lambda build, desc: pd.DataFrame(summary))
    return client


def test_designated_teams_reads_home_and_away(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, [{"homeTeamId": DET, "awayTeamId": DAL}])
    assert client.designated_teams("22500147") == (DET, DAL)


@pytest.mark.parametrize("summary", [
    [{"homeTeamId": None, "awayTeamId": None}],   # what V2 answers for the Las Vegas semifinals
    [{"gameId": "0022501229"}],                   # columns missing altogether
    [],                                           # no summary row
])
def test_designated_teams_refuses_a_summary_without_teams(tmp_path, monkeypatch, summary):
    client = _client(tmp_path, monkeypatch, summary)
    with pytest.raises(NBAClientError, match="0022501229"):
        client.designated_teams("0022501229")
