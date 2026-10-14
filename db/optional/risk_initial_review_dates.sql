-- OPTIONAL, run once. Gives existing risks a first "next review" date from today,
-- using the same default rhythm as RISK_REVIEW_INTERVALS
-- (very high 3, high 6, low 12, very low 12 months). Adjust the numbers to match
-- your .env if you changed them.
UPDATE risk_register
SET review_date = CURRENT_DATE +
  (CASE risk WHEN 'very high' THEN 3 WHEN 'high' THEN 6
             WHEN 'low' THEN 12 WHEN 'very low' THEN 12 END) * INTERVAL '1 month'
WHERE review_date IS NULL
  AND risk IN ('very high', 'high', 'low', 'very low');
