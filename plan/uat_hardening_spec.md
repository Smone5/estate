# UAT Hardening Specification

This document records product and engineering requirements discovered during local UAT. These requirements are not optional polish; they protect the first-admin and heir journeys from dead ends that were missed in the original plan.

## Scope

Applies to:

* local open-source setup and restart behavior
* first administrator onboarding
* heir invitation, onboarding, authentication, and re-entry
* government ID upload and Executor review
* email/manual invitation delivery
* dashboard live refresh expectations
* local UAT acceptance criteria

## Requirements

### UAT-01 Local Start Script & Persistence

The local startup path must preserve application state across restarts.

* `scripts/start_local.sh` must not delete or recreate the Postgres volume during ordinary startup.
* Restarting services must not force first-admin setup again.
* Restarting services must preserve sessions, heirs, assets, ID review state, and Admin credentials.
* Any destructive reset behavior must be an explicit, separately named command or flag with clear warnings.
* The script must print local URLs for the app, API, and local email inbox.

Acceptance:

* Start locally, create Admin, create session, register heir, stop services, start services again.
* Admin can log back in without setup.
* Heir and session data remain present.

### UAT-02 First Admin Re-Entry & Recovery

The Admin setup flow must distinguish between backup recovery and password recovery.

* The 24-word paper recovery key is for encrypted backup restore, not normal password login.
* The login page must not imply the recovery key can substitute for a forgotten Admin password unless a password-reset flow exists.
* If password recovery is implemented later, it must be a separate audited flow with explicit local-device proof or recovery-key proof.

Acceptance:

* Admin setup explains that the recovery phrase restores backups.
* Admin login makes password expectations clear.

### UAT-03 Heir Invitation Is Onboarding, Not Permanent Login

The invitation link is a first-entry onboarding credential, not the only long-term access method.

* First-time invite acceptance must ask the heir to create a password.
* The password must be Argon2-hashed in `users.pw_hash`.
* After onboarding, heirs must be able to sign in with email or display name plus password.
* Password login must work after `invite_token_expires_at`.
* If an heir never completes onboarding before the invite expires, the Executor must renew/send a new invitation.
* Invite-token resume may remain as a convenience while the token is unexpired, but it must not be the only re-entry path.

Acceptance:

* Register heir, accept invite, create password.
* Expire the invite token.
* Heir can still sign in at `/login` using email/display name plus password.
* Heir who never accepted invite cannot bypass onboarding using password login.

### UAT-04 Heir Browser Refresh & Session Restoration

Hard refresh must not strand an authenticated heir.

* The frontend must rehydrate heir state from the HTTP-only cookie using `/api/auth/me` plus `/api/heirs/me`.
* `/dashboard` must show a restoring state while cookie rehydration is in progress.
* If the cookie is expired/missing, the page must send the heir to the password login path, not only to the invitation link.

Acceptance:

* Heir logs in, hard-refreshes `/dashboard`, and remains on the dashboard if the cookie is valid.
* With an expired/missing cookie, heir sees a clear password sign-in path.

### UAT-04a Admin Browser Refresh & Session Restoration

Hard refresh must not log out an authenticated Admin.

* The frontend must rehydrate Admin state from the HTTP-only cookie using `/api/auth/me` before showing first-boot setup or the Admin login form.
* `/admin` must show a restoring state while cookie rehydration is in progress.
* The restore path must only accept `role == 'ADMIN'`; a valid Heir cookie must not open the Admin console.
* If the cookie is expired/missing, `/admin` may show the Admin login form or first-boot setup wizard according to `/api/setup/status`.
* Admin logout must call `POST /api/auth/logout`, clear the server cookie, clear local Admin session state, and remove any saved active Admin console session selection.

Acceptance:

* Admin logs in, hard-refreshes `/admin`, and remains in the Admin console if the cookie is valid.
* Hard-refreshing while viewing an estate session preserves the Admin authentication state and reloads the session list without forcing login.
* With an expired/missing cookie, Admin sees the normal login/setup gate.
* Clicking Admin logout clears the cookie and the saved active Admin console session.

### UAT-04b Optional Federated Login Journey

Federated login must be optional, standards-based, and compatible with open-source self-hosting.

* The first Admin account must always be creatable with a local password before SSO is enabled.
* Admin may configure a generic OIDC provider after local setup.
* Recommended self-hosted brokers are Keycloak or Authentik; Google, Apple, Facebook, Microsoft, and other providers should be connected through the broker or generic OIDC configuration.
* Admin SSO linking must require an already-authenticated Admin session.
* Heir SSO linking must be unavailable during invite acceptance and `PROFILE_HOLD`.
* Heir SSO linking must become available only after Executor identity approval (`identity_verified = true`, status `'ACTIVE'` or later).
* Matching provider email alone is not enough to claim an estate invite or existing account.
* Identity links must use stable `issuer + subject` identifiers, not email as the primary key.
* The system must retain at least one usable Admin login method before local password login can be disabled.

Acceptance:

* Admin configures OIDC, links their own external identity, logs out, and logs back in with SSO.
* Heir opens an invite, completes privacy/age/legal profile gates, and lands in `PROFILE_HOLD` without any external identity link.
* After Executor approval, the Heir links SSO from the authenticated dashboard/settings flow, logs out, and logs back in with SSO.
* A different Google/Apple/Facebook account with the same email display but different `issuer + subject` cannot claim an invite.

### UAT-05 Government ID Upload State

After an heir uploads an ID, the heir page must no longer ask for another ID unless the Executor rejects it.

* `POST /api/heirs/me/upload-id` must store the encrypted scan, set `identity_verified = false`, and expose enough profile state for the UI to know an ID has been submitted.
* The heir dashboard must show a waiting-for-Executor-review state while `userStatus == PROFILE_HOLD` and `id_scan_uri` exists.
* Upload controls must be hidden in that state.
* The state must survive hard refresh.

Acceptance:

* Heir uploads ID.
* Page changes to "submitted for Executor review."
* Hard refresh still shows the submitted/waiting state, not the upload prompt.

### UAT-06 Executor ID Review Visibility & Live Refresh

The Admin dashboard must surface ID submissions and the Heir dashboard must react to approval.

* Admin must see heirs awaiting ID review without manually hunting.
* Admin must be able to inspect the decrypted ID scan from the dashboard.
* Admin approval must transition the heir to `ACTIVE`, clear/purge the temporary scan, and seed valuations for live assets.
* Heir dashboard must poll or subscribe to profile/session updates so approval clears the hold without manual refresh.

Acceptance:

* Heir uploads ID.
* Admin dashboard shows a review-needed state.
* Admin approves.
* Heir dashboard updates within a short interval and unlocks once the session state permits it.

### UAT-07 Email Must Have Free/Open-Source Local Paths

The app must not require a paid email provider for local UAT or open-source operation.

* Local development must include a local SMTP inbox such as Mailpit.
* Invitation sending must surface delivery failures.
* Admin must be able to copy a complete invite message and paste it into any email client.
* Manual invite copy must include recipient, subject, invite URL, expiration, and short instructions.

Acceptance:

* Register heir with email.
* Email appears in local inbox when SMTP is available.
* If SMTP is unavailable, Admin can copy a complete invite message.

### UAT-08 Structured International Address Collection

Heir registration/profile addresses must not be a single freeform field only.

* Address fields must include address line 1, address line 2, city/locality, state/province/region, postal code, and country.
* The UI may still keep a composed `physical_address` for legacy display/export, but structured fields are the source of truth.
* Labels should support non-US wording where possible, e.g. "State/Province/Region" and "Postal/ZIP Code."

Acceptance:

* Admin can register heir using structured address fields.
* Heir profile API returns structured address fields.
* Export/GDPR output includes address data.

### UAT-09 Local UAT Script

The project must include a manual UAT script for a first administrator.

The script must cover:

1. start local services
2. create first Admin
3. write down backup recovery phrase
4. create an estate session
5. create/register heir
6. send or manually copy invite
7. accept invite as heir
8. create heir password
9. upload ID
10. inspect/approve ID as Admin
11. verify heir dashboard unlocks
12. hard-refresh heir dashboard
13. hard-refresh Admin dashboard
14. expire/ignore invite and log in via `/login`
15. create at least one asset and publish it
16. verify backup download/restore messaging

Acceptance:

* A non-developer can follow the script on a local machine and understand expected results at each checkpoint.

## Test Coverage Requirements

Backend tests must cover:

* heir password creation during invite verification
* password login after invite expiry
* password login rejection before onboarding
* ID upload state payload
* ID approval state transition
* local email failure behavior

Frontend tests must cover:

* heir password login page
* invite onboarding password fields
* dashboard cookie rehydration
* Admin dashboard cookie rehydration after hard refresh
* Admin logout clears the HTTP-only cookie and local Admin console selection
* ID submitted/waiting state after upload and after hard refresh
* Admin ID review visibility
* manual invite copy flow

## Security Notes

* Invitation URLs are bearer credentials and must be treated as sensitive.
* Invitation URLs should expire and should not be the permanent login method.
* Passwords must never be stored plaintext.
* HTTP-only cookies remain the session transport.
* Local UAT may use `secure=false` cookies on `localhost`; production/tunnel deployments must use HTTPS and secure cookies.
