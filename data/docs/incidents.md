---
tenant: default
title: Incident Response Runbook
---
# Incident response

## Severity levels

SEV1 means customers cannot place orders. Page the on-call engineer and the incident commander immediately. SEV2 means degraded performance with a workaround. SEV3 is everything else and is handled during business hours.

## Error codes

ERR_4021 means the payment gateway rejected the request because the idempotency key was reused. Do not retry with the same key; generate a new one. ERR_5003 means the inventory service timed out. Check the inventory service's connection pool before restarting anything.

## Communication

Post updates in the #incidents channel every 30 minutes for SEV1 and every hour for SEV2. The incident commander owns the customer status page.
