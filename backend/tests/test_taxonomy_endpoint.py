import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _TaxonomyConnection:
    def __init__(self, tracks, topics, subtopics):
        self.tracks = tracks
        self.topics = topics
        self.subtopics = subtopics
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.queries.append((sql, params or {}))

        if "FROM tracks" in sql:
            rows = sorted(
                self.tracks,
                key=lambda row: (row["track_name"], row["track_id"]),
            )
        elif "FROM topics" in sql:
            track_ids = set((params or {}).get("track_ids", []))
            rows = sorted(
                (row for row in self.topics if row["track_id"] in track_ids),
                key=lambda row: (row["topic_name"], row["topic_id"]),
            )
        elif "FROM subtopics" in sql:
            topic_ids = set((params or {}).get("topic_ids", []))
            rows = sorted(
                (row for row in self.subtopics if row["topic_id"] in topic_ids),
                key=lambda row: (row["subtopic_name"], row["subtopic_id"]),
            )
        else:
            raise AssertionError(f"Unexpected taxonomy query: {sql}")

        return _Result(rows)


class TaxonomyEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.tracks = [
            {"track_id": 2, "track_name": "Aptitude"},
            {"track_id": 1, "track_name": "Aptitude"},
            {"track_id": 3, "track_name": "Programming"},
        ]
        self.topics = [
            {"topic_id": 22, "topic_name": "Quantitative", "track_id": 2},
            {"topic_id": 21, "topic_name": "Quantitative", "track_id": 1},
            {"topic_id": 31, "topic_name": "Algorithms", "track_id": 3},
            {"topic_id": 90, "topic_name": "Unrelated", "track_id": 90},
        ]
        self.subtopics = [
            {"subtopic_id": 222, "subtopic_name": "Number systems", "topic_id": 22},
            {"subtopic_id": 221, "subtopic_name": "Number systems", "topic_id": 22},
            {"subtopic_id": 311, "subtopic_name": "Graphs", "topic_id": 31},
            {"subtopic_id": 901, "subtopic_name": "Excluded", "topic_id": 90},
        ]

    def _get_taxonomy(self, tracks=None, topics=None, subtopics=None):
        connection = _TaxonomyConnection(
            self.tracks if tracks is None else tracks,
            self.topics if topics is None else topics,
            self.subtopics if subtopics is None else subtopics,
        )
        with patch("app.main.engine.connect", return_value=connection):
            response = self.client.get("/taxonomy")
        self.assertEqual(response.status_code, 200, response.text)
        return response, connection

    def test_response_matches_hierarchy_and_preserves_order(self):
        response, connection = self._get_taxonomy()

        self.assertEqual(
            response.json(),
            [
                {
                    "track_id": 1,
                    "track_name": "Aptitude",
                    "topics": [
                        {
                            "topic_id": 21,
                            "topic_name": "Quantitative",
                            "subtopics": [],
                        }
                    ],
                },
                {
                    "track_id": 2,
                    "track_name": "Aptitude",
                    "topics": [
                        {
                            "topic_id": 22,
                            "topic_name": "Quantitative",
                            "subtopics": [
                                {"subtopic_id": 221, "subtopic_name": "Number systems"},
                                {"subtopic_id": 222, "subtopic_name": "Number systems"},
                            ],
                        }
                    ],
                },
                {
                    "track_id": 3,
                    "track_name": "Programming",
                    "topics": [
                        {
                            "topic_id": 31,
                            "topic_name": "Algorithms",
                            "subtopics": [
                                {"subtopic_id": 311, "subtopic_name": "Graphs"}
                            ],
                        }
                    ],
                },
            ],
        )
        self.assertEqual(len(connection.queries), 3)
        original_loop_query_count = (
            1
            + len(self.tracks)
            + sum(1 for topic in self.topics if topic["track_id"] in {1, 2, 3})
        )
        self.assertEqual(original_loop_query_count, 7)
        self.assertEqual(
            len(response.content),
            len(json.dumps(response.json(), separators=(",", ":")).encode()),
        )
        self.assertIn(b'"subtopics":[]', response.content)

    def test_no_tracks_returns_empty_list_after_one_query(self):
        response, connection = self._get_taxonomy(tracks=[])

        self.assertEqual(response.json(), [])
        self.assertEqual(len(connection.queries), 1)

    def test_no_topics_returns_tracks_with_empty_topic_lists(self):
        response, connection = self._get_taxonomy(topics=[], subtopics=[])

        self.assertEqual(
            response.json(),
            [
                {"track_id": 1, "track_name": "Aptitude", "topics": []},
                {"track_id": 2, "track_name": "Aptitude", "topics": []},
                {"track_id": 3, "track_name": "Programming", "topics": []},
            ],
        )
        self.assertEqual(len(connection.queries), 2)

    def test_no_subtopics_returns_topics_with_empty_subtopic_lists(self):
        response, connection = self._get_taxonomy(subtopics=[])

        self.assertEqual(
            response.json(),
            [
                {
                    "track_id": 1,
                    "track_name": "Aptitude",
                    "topics": [
                        {
                            "topic_id": 21,
                            "topic_name": "Quantitative",
                            "subtopics": [],
                        }
                    ],
                },
                {
                    "track_id": 2,
                    "track_name": "Aptitude",
                    "topics": [
                        {
                            "topic_id": 22,
                            "topic_name": "Quantitative",
                            "subtopics": [],
                        }
                    ],
                },
                {
                    "track_id": 3,
                    "track_name": "Programming",
                    "topics": [
                        {
                            "topic_id": 31,
                            "topic_name": "Algorithms",
                            "subtopics": [],
                        }
                    ],
                },
            ],
        )
        self.assertEqual(len(connection.queries), 3)


if __name__ == "__main__":
    unittest.main()
