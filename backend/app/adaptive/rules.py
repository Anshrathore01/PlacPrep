"""Central adaptive policy; selection is deterministic and uses no trained model.

Performance history contains selected MCQ answers from SUBMITTED attempts only.
The profile keeps the last 20 answered questions, the last 10 per topic, and a
bounded 200-300 answer history for trend comparison. Accuracy uses the
Beta-style prior (correct + 2) / (attempted + 4). Difficulty only changes
after five recent answers: below 45% shifts at most one step easier, 45%-75%
targets MEDIUM, and above 75% shifts at most one step harder from the latest
known difficulty. NULL difficulty remains NULL and is never inferred.

The candidate score is a weighted sum of normalized topic need, subtopic need,
difficulty fit, novelty, recent topic coverage, and sufficiently sampled time
signal. Its weights are centralized below and are not part of student
responses. The selector targets 70% personalized (exploitation) and 30%
underrepresented/cold-start (exploration), sorts deterministically, and limits
same-subtopic streaks to three where alternatives exist.

Candidates first exclude the last 30 seen question IDs and prefer the allowed
difficulty set. If the requested count cannot be filled, selection relaxes
recent-question exclusion, then difficulty preference, then both. Explicit
question type/topic/subtopic/difficulty filters and production eligibility
are never relaxed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AdaptiveConfig:
    recent_question_window: int = 30
    recent_answer_window: int = 20
    recent_topic_window: int = 10
    max_session_questions: int = 100
    minimum_topic_sample: int = 5
    minimum_recent_sample: int = 5
    minimum_time_sample: int = 3
    low_accuracy_threshold: float = 45.0
    high_accuracy_threshold: float = 75.0
    prior_correct: float = 2.0
    prior_total: float = 4.0
    exploration_ratio: float = 0.30
    unknown_dimension_need: float = 0.5
    unknown_difficulty_fit: float = 0.25
    trend_adjustment_limit: float = 0.15
    time_baseline_ratio: float = 0.75
    time_signal_range: float = 1.5
    coding_error_repeat_threshold: int = 2
    max_recommendations: int = 10
    max_candidate_pool: int = 1500
    max_same_subtopic_streak: int = 3
    candidate_weights: tuple[tuple[str, float], ...] = (
        ("topic_need", 0.25),
        ("subtopic_need", 0.20),
        ("difficulty_fit", 0.15),
        ("novelty", 0.15),
        ("coverage", 0.15),
        ("time_signal", 0.10),
    )


CONFIG = AdaptiveConfig()

DIFFICULTY_ORDER = ("EASY", "MEDIUM", "HARD")
DEFAULT_DIFFICULTIES = ("EASY", "MEDIUM")


def smoothed_accuracy(correct: int, attempted: int) -> float:
    """Conservative Beta prior: (correct + 2) / (attempted + 4)."""
    return (correct + CONFIG.prior_correct) / (attempted + CONFIG.prior_total) * 100.0


def preferred_difficulties(
    recent_accuracy: float | None,
    sample_size: int,
    current_difficulty: str | None,
) -> tuple[str, ...]:
    if sample_size < CONFIG.minimum_recent_sample or recent_accuracy is None:
        return DEFAULT_DIFFICULTIES

    if recent_accuracy < CONFIG.low_accuracy_threshold:
        if current_difficulty not in DIFFICULTY_ORDER:
            return ("EASY", "MEDIUM")
        index = DIFFICULTY_ORDER.index(current_difficulty)
        return tuple(DIFFICULTY_ORDER[max(0, index - 1):index + 1])

    if recent_accuracy > CONFIG.high_accuracy_threshold:
        if current_difficulty not in DIFFICULTY_ORDER:
            return ("MEDIUM", "HARD")
        index = DIFFICULTY_ORDER.index(current_difficulty)
        return tuple(DIFFICULTY_ORDER[index:min(len(DIFFICULTY_ORDER), index + 2)])

    return ("MEDIUM",)
