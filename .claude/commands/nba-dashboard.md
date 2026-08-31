Fetch and display an NBA player summary dashboard.

**Player:** $ARGUMENTS

Run the following command using the Bash tool:

```bash
python nba_dashboard.py "$ARGUMENTS"
```

If a season is not specified in `$ARGUMENTS`, the script defaults to the current season.
You can also pass a season explicitly, e.g. `/nba-dashboard LeBron James 2024-25`.

After running, present the output to the user. If any section fails (e.g. injury data
unavailable, player not found), explain the issue clearly and suggest fixes such as:
- Checking the spelling of the player name
- Trying a partial name match (e.g. "Jokic" instead of "Nikola Jokic")
- Verifying the season string format is `YYYY-YY`

The dashboard covers:
1. **Season averages.** PPG, RPG, APG, SPG, BPG, FG%, 3P%, FT%
2. **Last 5 & Last 10 game averages.** Rolling per-game stats
3. **Quarter-by-quarter breakdown.** PTS per quarter for last 5 games, with hot/cold pattern detection
4. **Recent game log.** Last 5 games with box score stats
5. **Team injury report.** Current injuries going into the next game
