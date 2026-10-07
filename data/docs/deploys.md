---
tenant: default
title: Deployment Guide
---
# Deployments

## Release windows

Production deploys happen Monday to Thursday between 10:00 and 16:00 local time. There are no deploys on Fridays or the day before a public holiday unless the change fixes a SEV1.

## Rollback

Every Cloud Run deploy keeps the previous revision. To roll back, send 100 percent of traffic to the previous revision with `gcloud run services update-traffic orders-api --to-revisions=PREVIOUS=100`. Rollbacks don't need a change ticket.

## Canary

New revisions start at 5 percent of traffic for 30 minutes. If the error rate stays under 1 percent, move to 50 percent, then 100 percent.
