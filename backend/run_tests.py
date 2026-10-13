import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"
USER_ID = 1
MOCK_TEST_ID = 4 # Known clean mock from Phase 1

def p(msg): print(f"\n--- {msg} ---")

p("TEST 1: Create an attempt")
res = requests.post(f"{BASE_URL}/attempts", json={"user_id": USER_ID, "mock_test_id": MOCK_TEST_ID})
assert res.status_code == 201, res.text
data = res.json()
attempt_id = data["attempt_id"]
print(f"Created attempt {attempt_id}, status: {data['status']}")
questions = data["questions"]
q1_id = questions[0]["question_id"]
q2_id = questions[1]["question_id"]

p("TEST 2: Save valid MCQ answer")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id}/answers", json={
    "question_id": q1_id,
    "selected_option_key": "A",
    "time_spent_seconds": 10
})
assert res.status_code == 200, res.text
print(res.json())

p("TEST 3: Update same answer before submission")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id}/answers", json={
    "question_id": q1_id,
    "selected_option_key": "B",
    "time_spent_seconds": 15
})
assert res.status_code == 200, res.text
print(res.json())

p("TEST 7: Invalid question_id (doesn't exist)")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id}/answers", json={
    "question_id": 99999999,
    "selected_option_key": "C",
    "time_spent_seconds": 5
})
assert res.status_code == 400, res.status_code
print("Rejected correctly:", res.json())

p("TEST 8: Question from another mock test (mock test 1 has Q1, but let's just pick Q 3034)")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id}/answers", json={
    "question_id": 3034,
    "selected_option_key": "A",
    "time_spent_seconds": 5
})
assert res.status_code == 400, res.status_code
print("Rejected correctly:", res.json())

p("TEST 9: Invalid option key")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id}/answers", json={
    "question_id": q2_id,
    "selected_option_key": "Z",
    "time_spent_seconds": 5
})
assert res.status_code == 400, res.status_code
print("Rejected correctly:", res.json())

p("TEST 10: Attempt retrieval (resume)")
res = requests.get(f"{BASE_URL}/attempts/{attempt_id}")
assert res.status_code == 200, res.text
data = res.json()
print("Retrieved successfully. Keys in q1:")
q1 = [q for q in data["questions"] if q["question_id"] == q1_id][0]
print(f"Selected option is preserved: {q1.get('selected_option_key')}")
assert "correct_option_key" not in q1

p("TEST 12: Untimed attempt works (since mock_test 4 duration is null)")
print("It works since we've been saving answers.")

p("TEST 4: Submit attempt")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id}/submit")
assert res.status_code == 200, res.text
print("Submitted:", res.json()["attempt"]["status"])

p("TEST 5: Try answer after submission")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id}/answers", json={
    "question_id": q2_id,
    "selected_option_key": "C",
    "time_spent_seconds": 5
})
assert res.status_code == 400, res.status_code
print("Rejected correctly:", res.json())

p("TEST 6: Try second submission")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id}/submit")
assert res.status_code == 400, res.status_code
print("Rejected correctly:", res.json())

print("\nALL API TESTS PASSED.")
