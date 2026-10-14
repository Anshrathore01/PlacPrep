# PlacPrep deployment

This deployment uses Aiven MySQL, Render for FastAPI, and Vercel for Next.js.
It does not import or reset the database. Complete the Aiven verification and
safe recovery described below before pointing a public API at it.

## Aiven verification and recovery

1. In Aiven, confirm the service is `Running`, and note the connection details.
   Use the existing `defaultdb` service and the `avnadmin` account.
2. Use a MySQL 8.4 compatible client and connect with TLS required. Enter the
   password only at the client's hidden prompt; do not put it in a command,
   shell history, chat, or logs:

   ```sh
   mysql --host=mysql-30b6cc96-placement-prep123.j.aivencloud.com \
     --port=13363 --user=avnadmin --password --ssl-mode=VERIFY_IDENTITY \
     --ssl-ca="/Users/anshrathore/placement-platform/backup/ca copy.pem" defaultdb
   ```

3. Run read-only inventory queries first:

   ```sql
   SELECT TABLE_TYPE, COUNT(*) AS object_count
   FROM information_schema.tables
   WHERE table_schema = DATABASE()
   GROUP BY TABLE_TYPE;
   SELECT TABLE_NAME, TABLE_ROWS
   FROM information_schema.tables
   WHERE table_schema = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
   ORDER BY TABLE_NAME;
   SHOW CREATE VIEW v_mock_question_content;
   SHOW CREATE VIEW v_practice_question_solutions;
   SELECT COUNT(*) FROM v_mock_question_content;
   SELECT COUNT(*) FROM v_practice_question_solutions;
   SELECT COUNT(*) FROM users;
   SELECT COUNT(*) FROM questions;
   SELECT COUNT(*) FROM mock_tests;
   SELECT COUNT(*) FROM mock_test_questions;
   SELECT COUNT(*) FROM coding_questions;
   SELECT COUNT(*) FROM coding_practice_progress;
   SELECT COUNT(*) FROM google_auth_nonces;
   ```

   Inspect keys and foreign keys with `SHOW CREATE TABLE <table_name>` for
   `users`, `questions`, `mock_tests`, `mock_test_questions`, `attempts`,
   `coding_questions`, `coding_practice_progress`, and Google-auth tables.
   `information_schema.TABLE_ROWS` is approximate for InnoDB; compare exact
   `COUNT(*)` results for important tables against the backup's inserts.
4. Both backup files were confirmed readable locally. The corrected copy has
   `SQL SECURITY INVOKER` view definitions. Keep the original untouched. Do
   not reimport all DDL/data. If verification identifies a specific missing
   object or row set, make a narrow, repeatable repair after reviewing the
   exact statements and their effects. Never drop or truncate existing data.
5. The application's existing local MySQL credentials are usable for a
   read-only inventory. All 31 local base-table counts match the corrected
   backup's INSERT row counts; both local views execute and return 864 and 311
   rows. The separate interactive `root` login failure therefore does not
   prevent local comparison. Aiven still must be inventoried with the secure
   MySQL password prompt; previously observed counts on a remote connection
   were partial evidence and do not prove all tables match.

## Render backend

The repository includes `render.yaml`; use **New > Blueprint** in Render and
select this GitHub repository. The service root is `backend`, the start command
is `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and health checks use
`/health`.

Before creating the service, add a Render **secret file** named `aiven-ca.pem`
with the contents of the valid Aiven CA at `backup/ca copy.pem`. The service
sets `DB_SSL_CA_CERT=/etc/secrets/aiven-ca.pem`; PyMySQL verifies its chain and
hostname. Set the Blueprint's prompted secrets in the Render dashboard:

- `DB_PASSWORD`: Aiven password
- `JWT_SECRET`: let Render generate a fresh random value (or retain the
  Blueprint-generated one)
- `GOOGLE_CLIENT_ID`: Google Web OAuth client ID
- `GEMINI_API_KEY`: Gemini API key
- `FRONTEND_ORIGINS`: exact deployed Vercel origin, e.g.
  `https://placprep.vercel.app` (no trailing slash); add any production alias
  actually used by students

Add the production Render API URL as `NEXT_PUBLIC_API_BASE_URL` in Vercel,
for example `https://placprep-api.onrender.com` after confirming the URL Render
assigned. Set `NEXT_PUBLIC_GOOGLE_CLIENT_ID` to the same Web client ID.

`backend/migrations/012_google_auth.sql` and earlier migrations must be checked
against the existing Aiven schema before application. Apply only missing
migrations using the Aiven account and migration procedure; do not assume the
database is empty or rerun seed/import scripts. `/health` is liveness only;
`/test-db` reports database connectivity without exposing driver details.

## Vercel frontend

Import the same GitHub repository into Vercel and set **Root Directory** to
`frontend`. Use the normal Next.js framework preset and configure:

- `NEXT_PUBLIC_API_BASE_URL` = the confirmed Render API origin (no trailing
  slash)
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID` = the Google Web OAuth client ID

Deploy a Preview first, verify the generated hostname, and then set the final
production domain in Vercel. Add that exact HTTPS origin to Google's authorized
JavaScript origins and to Render's `FRONTEND_ORIGINS`.

## Google OAuth client

In Google Cloud Console, select or create the project that will own PlacPrep's
OAuth client. Configure the OAuth consent screen with the app name, support
email, audience, and developer contact; add test users while the app is in
testing. Create an OAuth client ID with application type **Web application**.
Add these **Authorized JavaScript origins**:

- `http://localhost:3000` for local development
- `http://localhost` if you serve the app on the default HTTP port
- The exact Vercel production origin, such as `https://<your-production-domain>`
- Any Vercel preview origin you will actively test (each origin must be exact)

This app uses Google Identity Services to return an ID credential to the
frontend and then posts it to the backend. It does not use a redirect-based
authorization-code callback, so no **Authorized redirect URI** is required for
this implementation. Put only the Web client ID in the frontend's
`NEXT_PUBLIC_GOOGLE_CLIENT_ID` and backend's `GOOGLE_CLIENT_ID`; there is no
client secret in this flow. For public production use, follow Google's
verification requirements if the consent screen requests sensitive scopes.

## Local commands

Backend (from `backend/`, with a configured `.env`):

```sh
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend (from `frontend/`, with `.env.local`):

```sh
npm ci
npm run dev
```

Use `https://` production URLs and keep all private values in Render/Vercel
settings or ignored local environment files. Do not commit `backup/*.pem`.

## Hosting limitations

Render free web services can spin down after inactivity and cold-start, and
free resources/storage are limited. Vercel plan limits and Aiven service tier
limits also apply. A public launch should use service tiers with suitable
availability, database backups, storage, and resource limits; application
uploads must not depend on an ephemeral Render filesystem.
