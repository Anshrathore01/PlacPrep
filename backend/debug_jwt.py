import jwt

from app.auth.security import JWT_SECRET

token = "replace_me"
try:
    print(jwt.decode("YOUR_TOKEN_HERE", JWT_SECRET, algorithms=["HS256"]))
except Exception as e:
    print(e)
