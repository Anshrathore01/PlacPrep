import requests
import time

BASE_URL = "http://127.0.0.1:8000"
MOCK_TEST_ID = 4

def p(msg): print(f"\n--- {msg} ---")

s1_email = "studenta@example.com"
s1_pass = "securepass1"
s2_email = "studentb@example.com"
s2_pass = "securepass2"
admin_email = "admin@example.com"
admin_pass = "adminpass"

p("TEST 1: Register student A")
res = requests.post(f"{BASE_URL}/auth/register", json={
    "email": s1_email, "password": s1_pass, "display_name": "Student A"
})
assert res.status_code == 201, res.text
print("Success")

p("TEST 2: Register same email again")
res = requests.post(f"{BASE_URL}/auth/register", json={
    "email": s1_email, "password": s1_pass, "display_name": "Student A Duplicate"
})
assert res.status_code == 409, res.text
print("Rejected correctly:", res.json())

p("TEST 3: Register student B")
res = requests.post(f"{BASE_URL}/auth/register", json={
    "email": s2_email, "password": s2_pass, "display_name": "Student B"
})
assert res.status_code == 201, res.text
print("Success")

p("Register Admin (direct DB for role)")
import subprocess
subprocess.run(['mysql', '-u', 'root', '-p12345678', 'placement_platform', '-e', f"UPDATE users SET role='ADMIN' WHERE email='{admin_email}'"])
res = requests.post(f"{BASE_URL}/auth/register", json={
    "email": admin_email, "password": admin_pass, "display_name": "Admin"
})
subprocess.run(['mysql', '-u', 'root', '-p12345678', 'placement_platform', '-e', f"UPDATE users SET role='ADMIN' WHERE email='{admin_email}'"])

p("TEST 4: Login student A")
res = requests.post(f"{BASE_URL}/auth/login", json={"email": s1_email, "password": s1_pass})
assert res.status_code == 200, res.text
token_a = res.json()["access_token"]
headers_a = {"Authorization": f"Bearer {token_a}"}
print("Success, got token")

p("TEST 5: Login with wrong password")
res = requests.post(f"{BASE_URL}/auth/login", json={"email": s1_email, "password": "wrong"})
assert res.status_code == 401, res.status_code
print("Rejected correctly")

p("TEST 6: Call protected endpoint without token")
res = requests.get(f"{BASE_URL}/auth/me")
assert res.status_code == 403 or res.status_code == 401, res.status_code
print("Rejected correctly")

p("TEST 7: Call protected endpoint with invalid token")
res = requests.get(f"{BASE_URL}/auth/me", headers={"Authorization": "Bearer bad_token"})
assert res.status_code == 401, res.status_code
print("Rejected correctly")

p("Login student B")
res = requests.post(f"{BASE_URL}/auth/login", json={"email": s2_email, "password": s2_pass})
token_b = res.json()["access_token"]
headers_b = {"Authorization": f"Bearer {token_b}"}

p("TEST 8: Student A creates attempt")
res = requests.post(f"{BASE_URL}/attempts", json={"mock_test_id": MOCK_TEST_ID}, headers=headers_a)
assert res.status_code == 201, res.text
data = res.json()
attempt_id_a = data["attempt_id"]
print(f"Created attempt {attempt_id_a}")

p("TEST 9: Student A retrieves own attempt")
res = requests.get(f"{BASE_URL}/attempts/{attempt_id_a}", headers=headers_a)
assert res.status_code == 200, res.text
print("Success")

p("TEST 10: Student B attempts to retrieve student A's attempt")
res = requests.get(f"{BASE_URL}/attempts/{attempt_id_a}", headers=headers_b)
assert res.status_code == 403 or res.status_code == 404, res.text
print("Rejected correctly:", res.json())

q_id = data["questions"][0]["question_id"]

p("TEST 11: Student B attempts to submit an answer to A's attempt")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id_a}/answers", json={
    "question_id": q_id, "selected_option_key": "A", "time_spent_seconds": 10
}, headers=headers_b)
assert res.status_code == 403, res.text
print("Rejected correctly:", res.json())

p("TEST 12: Student A answers own attempt")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id_a}/answers", json={
    "question_id": q_id, "selected_option_key": "A", "time_spent_seconds": 10
}, headers=headers_a)
assert res.status_code == 200, res.text
print("Success")

p("TEST 13: Student A submits own attempt")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id_a}/submit", headers=headers_a)
assert res.status_code == 200, res.text
print("Success")

p("TEST 14: Student B cannot submit A's submitted attempt")
res = requests.post(f"{BASE_URL}/attempts/{attempt_id_a}/submit", headers=headers_b)
assert res.status_code == 403 or res.status_code == 404, res.text
print("Rejected correctly:", res.json())

p("TEST 15: Student tries admin endpoint")
res = requests.get(f"{BASE_URL}/admin/mcq-health", headers=headers_a)
assert res.status_code == 403, res.text
print("Rejected correctly:", res.json())

p("TEST 16: Admin login")
res = requests.post(f"{BASE_URL}/auth/login", json={"email": admin_email, "password": admin_pass})
assert res.status_code == 200, res.text
token_admin = res.json()["access_token"]
headers_admin = {"Authorization": f"Bearer {token_admin}"}
print("Success")

p("TEST 17: Admin accesses admin/mcq-health")
res = requests.get(f"{BASE_URL}/admin/mcq-health", headers=headers_admin)
assert res.status_code == 200, res.text
print("Success")

p("TEST 18: Inactive account attempts login/access")
subprocess.run(['mysql', '-u', 'root', '-p12345678', 'placement_platform', '-e', f"UPDATE users SET is_active=0 WHERE email='{s2_email}'"])
res = requests.post(f"{BASE_URL}/auth/login", json={"email": s2_email, "password": s2_pass})
assert res.status_code == 403, res.status_code
print("Login rejected correctly:", res.json())

res = requests.get(f"{BASE_URL}/auth/me", headers=headers_b)
assert res.status_code == 403, res.status_code
print("Token access rejected correctly:", res.json())

print("\nALL AUTH TESTS PASSED.")
