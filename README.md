# Auction API Service

Public HTTP API for current and history lots from auction sites (Copart/IAAI).

## Base path

All public endpoints are under:

```
/public/v1
```

## Current lots

```
GET /public/v1/lot/current
```

Query params:

- `site` (required): `1`, `2`, `copart`, `iaai`, or `all`
- `make`
- `model`
- `vehicle_type`
- `year_from`, `year_to`
- `auction_date_from`, `auction_date_to` (format: `YYYY-MM-DD`)
- `transmission` (repeatable)
- `status` (repeatable)
- `drive` (repeatable)
- `damage_pr` (repeatable)
- `document` (repeatable)
- `odometer_min`, `odometer_max`
- `seller_type` (`insurance` or `dealer`)
- `sort` (`auction_date` or `created_at`)
- `direction` (`ASC` or `DESC`)
- `page` (default `1`)
- `size` (default `10`, max `30`)
- `buy_now`
- `fuel` (repeatable)
- `auction_type` (only for `site=2`, supported value: `timed`)

Example:

```
/public/v1/lot/current?site=2&auction_type=timed
```

Notes:

- `auction_type=timed` is **only** allowed when `site=2` (IAAI). For other sites the API returns a 422 validation error.
