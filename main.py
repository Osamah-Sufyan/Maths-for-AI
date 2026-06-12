import csv
import math
from pathlib import Path
import unicodedata


TOP_LEAGUE_WEIGHTS = {
    "Premier League": 1.00,
    "La Liga": 0.95,
    "Bundesliga": 0.90,
    "Serie A": 0.88,
    "Ligue 1": 0.82,
}

LEAGUES_DIR = Path("leagues")
TEAMS_DIR = Path("teams")
FIFA_LOGISTIC_MIDPOINT = 1500.0
FIFA_LOGISTIC_STEEPNESS = 0.006
DRAW_THRESHOLD = 7.0

TEAM_FILE_ALIASES = {
    "bosnia and herzegovina": "bosnia",
    "united states": "usa",
}

CLUB_ALIASES = {
    ("Premier League", "arsenal"): "arsenal",
    ("Premier League", "bournemouth"): "afc bournemouth",
    ("Premier League", "everton"): "everton",
    ("Premier League", "fulham"): "fulham",
    ("Premier League", "newcastle united"): "newcastle united",
    ("Serie A", "milan"): "ac milan",
}


def get_fifa_points(team_name: str) -> float:
    """
    Ask the user to enter FIFA ranking points in the terminal.
    Higher FIFA ranking points are better.
    Example: Argentina could be around 1900 points.
    """
    while True:
        try:
            points = float(input(f"Enter FIFA ranking points for {team_name}: "))
            if points <= 0:
                print("FIFA ranking points must be positive.")
                continue
            return points
        except ValueError:
            print("Please enter a valid number.")


def normalize_score(value: float, max_value: float) -> float:
    """
    Converts a positive value into a capped normalized score from 0.0 to 1.0.
    """
    if max_value <= 0:
        return 0.0
    return max(0.0, min(value / max_value, 1.0))


def fifa_points_score(points: float) -> float:
    """
    Converts FIFA ranking points into a normalized score using a logistic curve.

    This amplifies differences around typical competitive teams and flattens
    very high or very low point totals.
    """
    return 1 / (
        1 + math.exp(-FIFA_LOGISTIC_STEEPNESS * (points - FIFA_LOGISTIC_MIDPOINT))
    )


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("&", "and")

    for token in [".", ",", "-", "'", " fc", " afc", " cf"]:
        text = text.replace(token, " ")

    return " ".join(text.split())


def team_csv_path(team_name: str, teams_dir: Path = TEAMS_DIR) -> str:
    normalized_team_name = normalize_name(team_name)
    team_file_stem = TEAM_FILE_ALIASES.get(normalized_team_name, normalized_team_name)
    filename = f"{team_file_stem.replace(' ', '_')}.csv"
    csv_path = teams_dir / filename

    if csv_path.exists():
        return str(csv_path)

    matches = sorted(teams_dir.glob(f"group_*/{filename}"))
    if matches:
        return str(matches[0])

    raise FileNotFoundError(
        f"Could not find CSV for {team_name}. Expected {csv_path} "
        f"or a grouped path like {teams_dir}/group_*/{filename}"
    )


def club_position_score(position: int, max_position: int) -> float:
    """
    Converts club league position into a normalized score.

    1st place gets 1.0.
    Last place stays above zero because being in a top league still has value.
    """
    if position < 1:
        position = max_position
    if position > max_position:
        position = max_position

    return (max_position - position + 1) / max_position


def load_club_scores(leagues_dir: Path = LEAGUES_DIR) -> dict[tuple[str, str], float]:
    """
    Reads league ranking CSV files and returns normalized club scores.
    """
    club_scores = {}

    for csv_path in leagues_dir.glob("*.csv"):
        with csv_path.open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))

        if not rows:
            raise ValueError(f"{csv_path} is empty.")

        required_columns = {"league", "club", "position"}
        missing = required_columns - set(rows[0].keys())

        if missing:
            raise ValueError(f"Missing columns in {csv_path}: {missing}")

        rows_by_league = {}
        for row in rows:
            league = str(row["league"]).strip()
            rows_by_league.setdefault(league, []).append(row)

        for league, league_rows in rows_by_league.items():
            league_weight = TOP_LEAGUE_WEIGHTS.get(league, 0.0)
            max_position = max(int(row["position"]) for row in league_rows)

            for row in league_rows:
                club = normalize_name(row["club"])
                position_score = club_position_score(int(row["position"]), max_position)
                club_scores[(league, club)] = league_weight * position_score

    return club_scores


def get_club_score(row, club_scores: dict[tuple[str, str], float]) -> float:
    """
    Gives one player a score based on his club's normalized top-league ranking.
    """
    league = str(row["top_league"]).strip()
    club = normalize_name(row["club"])

    if league in {"", "None", "nan"} or league not in TOP_LEAGUE_WEIGHTS:
        return 0.0

    club = CLUB_ALIASES.get((league, club), club)

    direct_score = club_scores.get((league, club))
    if direct_score is not None:
        return direct_score

    # Handles common short names such as Milan -> AC Milan or Betis -> Real Betis.
    for (score_league, score_club), score in club_scores.items():
        if score_league == league and (club in score_club or score_club in club):
            return score

    return 0.0


def squad_strength(csv_path: str) -> float:
    """
    Reads team player CSV and returns normalized squad strength from 0.0 to 1.0.
    """
    with Path(csv_path).open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError(f"{csv_path} is empty.")

    required_columns = {"player", "top_league", "club"}
    missing = required_columns - set(rows[0].keys())

    if missing:
        raise ValueError(f"Missing columns in {csv_path}: {missing}")

    club_scores = load_club_scores()
    player_scores = [get_club_score(row, club_scores) for row in rows]

    average_score = sum(player_scores) / len(player_scores)
    top_league_player_ratio = sum(score > 0 for score in player_scores) / len(player_scores)

    # Combine quality and quantity while keeping the result normalized.
    strength = 0.75 * average_score + 0.25 * top_league_player_ratio

    return strength


def team_total_score(team_name: str, csv_path: str) -> float:
    fifa_points = get_fifa_points(team_name)

    fifa_score = fifa_points_score(fifa_points)
    squad_score = squad_strength(csv_path)

    # Main weighted formula
    total = 100 * (0.55 * fifa_score + 0.45 * squad_score)

    print(f"\n{team_name}")
    print(f"FIFA points score: {100 * fifa_score:.2f}")
    print(f"Squad score:       {100 * squad_score:.2f}")
    print(f"Normalized score:  {total:.2f}")

    return total


def predict_match(team_a: str, csv_a: str, team_b: str, csv_b: str):
    score_a = team_total_score(team_a, csv_a)
    score_b = team_total_score(team_b, csv_b)

    print("\nPrediction")
    print("-" * 30)

    diff = abs(score_a - score_b)

    if diff <= DRAW_THRESHOLD:
        prediction = "draw is most likely"
    elif score_a > score_b:
        prediction = f"{team_a} is likely to win"
    else:
        prediction = f"{team_b} is likely to win"

    if diff <= DRAW_THRESHOLD:
        confidence = "Very close"
    elif diff < 10:
        confidence = "Slight advantage"
    elif diff < 20:
        confidence = "Moderate advantage"
    else:
        confidence = "Strong advantage"

    print(f"{team_a}: {score_a:.2f}")
    print(f"{team_b}: {score_b:.2f}")
    print(f"Score difference: {diff:.2f}")
    print(f"Prediction: {prediction}")
    print(f"Confidence: {confidence}")


if __name__ == "__main__":
    team_a = input("Enter Team A name: ")
    csv_a = team_csv_path(team_a)

    team_b = input("Enter Team B name: ")
    csv_b = team_csv_path(team_b)

    predict_match(team_a, csv_a, team_b, csv_b)
