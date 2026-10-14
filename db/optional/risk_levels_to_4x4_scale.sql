-- OPTIONAL, run once. Moves risks from the old five-level scale to the 4x4 levels.
--   critical -> very high, moderate -> low   (low and high are unchanged)
-- Risks that have likelihood and impact set are recalculated by the app anyway.
-- Review the mapping first: if you would rather not underestimate old "moderate"
-- risks, change 'low' below to 'high'.
UPDATE risk_register SET risk = 'very high' WHERE risk = 'critical';
UPDATE risk_register SET risk = 'low'       WHERE risk = 'moderate';
