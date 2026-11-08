# Research v4 glossary (business definitions used by the independent oracle)

This file is the written contract for gold answers. `backend/eval/oracle_csv.py` implements it directly on the
raw CSV files in `data/landing/` with DuckDB. It does not read the ETL mart, `catalog/product_events.yaml`, or the
v3 generator, so an agreement between the oracle and the PostgreSQL gold SQL is evidence about the ETL mapping
and the gold SQL, not a restatement of one author's convention.

## Event rows (what counts as "an event")

**Cosmetics Shop** (`data/landing/cosmetics_shop/*.csv`, REES46 export)
- One event per raw row after dropping exact duplicate rows and rows with no time, user or event type.
- Event name: `event_type` (`view`, `cart`, `remove_from_cart`, `purchase`).
- Day: the UTC calendar date of `event_time`.
- User: `user_id`. Session: `user_session`.
- Product category: the text before the first `.` in `category_code` (NULL when empty).
- Revenue: `price` on `purchase` rows with `price > 0`, in USD. All other rows have no revenue.

**Olist** (`data/landing/olist_marketplace/*.csv`, relational orders). Timestamps are local Brazilian time with
no zone; they are read as UTC as written, so the calendar date is the date in the file.
Every event belongs to the customer's `customer_unique_id`. Orders whose customer is unknown produce no events.
- `order_purchased`: one per order item; day = order purchase date; revenue = item `price` if `price > 0`;
  category = English category name (fallback: Portuguese name) of the item's product, NULL when unknown.
- `order_approved`: one per order with an approval time (day = approval date).
- `order_shipped`: one per order with a carrier handover time (day = that date).
- `order_delivered`: one per order with a customer delivery time (day = that date).
- `order_canceled`: one per order whose status is `canceled`; day = purchase date (Olist has no cancel time).
- `payment_made`: one per payment row; day = order purchase date; revenue = `payment_value` if `> 0`.
- `review_submitted`: one per distinct (review, order); day = review creation date.
- Lifecycle events (everything except `order_purchased`) carry no product category.
- Olist has no sessions and no product views.

## Metrics

Computed over the event rows that satisfy the question's filters.

| Metric | Definition |
|---|---|
| events | number of event rows |
| users | distinct users |
| sessions | distinct non-empty sessions (Cosmetics only) |
| viewers | distinct users with a `view` event (Cosmetics only) |
| purchases | number of purchase rows (`purchase` / `order_purchased`); an item line, not an order |
| buyers | distinct users with a purchase row |
| revenue | sum of revenue over purchase rows; 0 when there are none; excludes Olist payments and freight |
| buyer_conversion_rate | buyers divided by users over the same rows; NULL when there are no users |

## Breakdowns and ranking

- A breakdown groups the filtered rows by the chosen field; a group is a distinct value of that field (NULL is a
  group). For `viewers`, `purchases`, `buyers` and `revenue`, only the rows of the matching event type take part,
  so a group with no such rows does not appear.
- "Top k" sorts by the metric descending, then by the group value ascending with NULL last, and keeps k rows.
- A plain breakdown is sorted by the group value ascending with NULL last.

## Not covered

Orders (as opposed to item lines), average order value, delivery or review metrics, currency conversion, and
causal claims are outside the scope of these gold answers.
