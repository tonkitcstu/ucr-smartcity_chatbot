# API UCR Chatbot

Postman variables: `{{base}}` is the address of the machine that runs the app (your own machine: `http://localhost:8000`). `{{key}}` is `DASHBOARD_API_KEY` in `.env`.

| # | Route | What it does | Who can call it |
|---|---|---|---|
| 1 | `POST {{base}}/webhook/line` | gets messages and events from LINE | LINE only, checked by LINE's signature |
| 2 | `GET {{base}}/health` | PostgreSQL, Redis, worker and sweeper are up | anyone |
| 3 | `GET {{base}}/api/dashboard/reports` | reports, newest first, with filters | API key |
| 4 | `GET {{base}}/api/dashboard/reports/:report_id` | one report | API key |
| 5 | `GET {{base}}/api/dashboard/attachments/:attachment_id` | one photo file | API key |
| 6 | `GET {{base}}/api/dashboard/transcripts/:session_id` | the whole chat of one session | API key |

## API key (routes 3 to 6)

Header: `Authorization: Bearer <key>`

Postman: in the collection's Authorization tab, choose Auth Type `Bearer Token` and set Token to `{{key}}`. Each request inside uses `Inherit auth from parent`.

| Response | When |
|---|---|
| 401 `{"detail": "Invalid API key"}` | no key, wrong key, or no `Bearer` before the key |
| 503 `{"detail": "DASHBOARD_API_KEY is not set"}` | the machine has no `DASHBOARD_API_KEY` |

## 3. Reports: filters

Every filter is optional. With more than one filter, a report must match all of them. Dates use the time the report was made (`created_at`), Thai time.

| Filter | Value | Meaning |
|---|---|---|
| `date` | `YYYY-MM-DD` | made on that day |
| `start_date` | `YYYY-MM-DD` | made on that day or later |
| `end_date` | `YYYY-MM-DD` | made on that day or earlier |
| `tag` | text | has this exact tag |
| `severity` | `low`, `medium` or `high` | has this severity |
| `limit` | 1 to 200, default 20 | how many, newest first |

Paste into Postman:

```
{{base}}/api/dashboard/reports
{{base}}/api/dashboard/reports?date=2026-10-25
{{base}}/api/dashboard/reports?start_date=2026-10-01
{{base}}/api/dashboard/reports?end_date=2026-10-25
{{base}}/api/dashboard/reports?start_date=2026-10-01&end_date=2026-10-31
{{base}}/api/dashboard/reports?tag=น้ำท่วม
{{base}}/api/dashboard/reports?severity=high
{{base}}/api/dashboard/reports?limit=50
{{base}}/api/dashboard/reports?tag=น้ำท่วม&severity=high&start_date=2026-10-01&end_date=2026-10-31&limit=200
```

| Response | When |
|---|---|
| 200, a list of reports, `[]` when nothing matches | normal |
| 422 | a date is not `YYYY-MM-DD`, `severity` is not one of the 3 values, or `limit` is outside 1 to 200 |

## 4 to 6. Routes with an ID

`:name` in Postman is a variable in the address. Fill it in the Path Variables table on the Params tab.

```
{{base}}/api/dashboard/reports/:report_id
{{base}}/api/dashboard/attachments/:attachment_id
{{base}}/api/dashboard/transcripts/:session_id
```

| ID | Where to get it |
|---|---|
| `report_id` | `report_id` in the report list |
| `attachment_id` | `attachments[].attachment_id` in a report, or `attachment.attachment_id` in a transcript |
| `session_id` | `session_id` in a report |

| Response | When |
|---|---|
| 200 | found · route 5 gives an `image/jpeg` file, not JSON |
| 404 `Report not found`, `Attachment not found` or `Transcript not found` | no such ID · route 5 also when the file is not on disk |
| 422 | the ID is not a UUID |

## Response JSON

One report, from routes 3 and 4:

| Field | Type | Meaning |
|---|---|---|
| `report_id` | UUID | this report |
| `session_id` | UUID | the chat it came from, for route 6 |
| `user_id` | UUID | the reporter, never their LINE ID |
| `desc` | text | 2 to 4 sentences: what happened, where, how often, who it affects, in the reporter's words |
| `tags` | list of text | 1 to 3 short topic words, for example น้ำท่วม (flood), ขยะ (garbage) · used by the `tag` filter |
| `severity` | `low`, `medium` or `high` | how serious |
| `affected_groups` | list | who is affected: `elderly`, `children`, `disabled`, `pedestrians`, `drivers`, `workers`, `residents` |
| `time_periods` | list | when it happens: `morning`, `midday`, `evening`, `night` |
| `place` | text or `null` | the place in the reporter's words, for example หน้าวัด (in front of the temple) · `null` when they did not say |
| `lat`, `lng` | number or `null` | from the location pin the reporter sent |
| `attachments` | list | photos: `attachment_id` and `url` for route 5 |
| `started_at` | time, Thai time | when the chat started |
| `created_at` | time, Thai time | when the report was made, after the chat closed |

One message, from route 6, oldest first:

| Field | Type | Meaning |
|---|---|---|
| `message_id` | UUID | this message |
| `role` | `user` or `assistant` | reporter or bot |
| `type` | `text`, `image`, `location` or `sticker` | kind of message |
| `content` | text or `null` | text, or LINE's words for a sticker |
| `lat`, `lng` | number or `null` | for `location` |
| `status` | `pending`, `answered` or `skipped` | `skipped`: waiting when the chat got too full, or sent while it was paused · the analyser does not read it |
| `attachment` | object or `null` | for `image`: `attachment_id` and `url` for route 5 |
