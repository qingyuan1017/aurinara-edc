# Shared platform control plane

Aurinara EDC remains independently deployable and retains its clinical, CTMS, PV, and
immutable domain audit data. The independent `aurinara-platform` service owns OIDC
identity mappings, canonical study identity, memberships, authorization policy, and the
opaque object catalog. There are no cross-database foreign keys or shared ORM packages.

## Runtime modes

- `disabled` preserves existing local authentication and permissions for rollout.
- `shadow` compares control-plane decisions with local enforcement and logs mismatches.
- `enforced` uses control-plane decisions as authority and fails closed with `503` after
  any unexpired positive cache entry has elapsed.

The maximum positive cache window is 60 seconds. User and membership events invalidate
cached decisions early. Applied event IDs and aggregate sequences make canonical user,
study, and membership projections idempotent and safe under replay or reordering.

Canonical study events update identity and registry fields only. EDC continues to own
protocol metadata, clinical status, sites, versions, subjects, and clinical data.
Authorization decision IDs and policy versions are copied into immutable EDC audit
events. Attachments carrying `platform_object_id` are downloaded through the gateway;
storage keys and credentials never reach the frontend.

## Migration sequence

1. Apply migration `0053` and configure the generic OIDC issuer, API audience, JWKS URL,
   and a dedicated API service account.
2. Prepare a reviewed user identity map. Never infer an issuer/subject for a local
   password account.
3. Export a strict snapshot from `backend/`:

   ```powershell
   python -m scripts.export_platform_snapshot `
     --identity-map ..\migration\reviewed-identities.json `
     --output ..\migration\edc-platform-snapshot.json
   ```

4. Import the snapshot into `aurinara-platform`, subscribe the projection worker to its
   event stream, and run authorization in shadow mode.
5. Reconcile every user, study, scoped role, attachment, and decision mismatch before
   enabling enforced mode. Missing or conflicting mappings block cutover.
6. Keep legacy files throughout dual-read and rollback windows. Set
   `platform_object_id` only after catalog registration and checksum/retention checks.

The service account needs `platform.authorization.decide` and the applicable
`aurinara-edc.object.*` permissions. End-user tokens are validated locally against JWKS;
no per-request authentication callback is made to the identity provider.
