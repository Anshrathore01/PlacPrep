import unittest

from fastapi import HTTPException

from app.services.blueprint_service import _allocate_unique_questions


class BlueprintSelectionTests(unittest.TestCase):
    def test_overlapping_rules_allocate_distinct_questions(self):
        rules = [
            {
                "blueprint_rule_id": 1,
                "question_count": 1,
                "points": 1,
                "selection_weight": 1,
            },
            {
                "blueprint_rule_id": 2,
                "question_count": 1,
                "points": 2,
                "selection_weight": 1,
            },
        ]

        selections = _allocate_unique_questions(
            rules,
            [[100, 101], [100]],
        )

        question_ids = [
            question_id
            for selection in selections
            for question_id in selection["question_ids"]
        ]
        self.assertEqual(len(question_ids), 2)
        self.assertEqual(len(set(question_ids)), 2)
        self.assertEqual(selections[1]["question_ids"], [100])

    def test_overlapping_rules_fail_when_distinct_pool_is_too_small(self):
        rules = [
            {"blueprint_rule_id": 1, "question_count": 1, "points": 1},
            {"blueprint_rule_id": 2, "question_count": 1, "points": 1},
        ]

        with self.assertRaises(HTTPException) as raised:
            _allocate_unique_questions(rules, [[100], [100]])

        self.assertEqual(raised.exception.status_code, 409)

    def test_blueprint_question_limit_is_enforced(self):
        rules = [
            {"blueprint_rule_id": 1, "question_count": 101, "points": 1},
        ]

        with self.assertRaises(HTTPException) as raised:
            _allocate_unique_questions(rules, [list(range(101))])

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
