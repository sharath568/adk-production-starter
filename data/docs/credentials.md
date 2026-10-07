---
tenant: default
title: Secrets and Credential Rotation
---
# Credential rotation

## Database passwords

Database passwords live in Secret Manager under `orders-db-password`. They rotate every 90 days. To rotate early, add a new secret version, roll the service so it picks up the new version, then disable the old version after 24 hours.

## Service accounts

Never create service account keys. Workloads on Cloud Run use their attached service account. Engineers use `gcloud auth login` and impersonation for one-off admin tasks.
