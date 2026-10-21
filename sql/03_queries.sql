-- The Review 2 queries. The "Queries" page in the app reads this file,
-- so if you change a query here it changes in the app too.
-- Format: each block starts with "-- name:" and can have "-- note:" lines.

-- name: 7.1 SELECT | All buildings
-- note: Simplest query, a few columns from one table.
SELECT building_id, building_name, floors, total_area_sqft
FROM buildings;

-- name: 7.2 WHERE | Meters that are active right now
-- note: The library steam meter (1008) is Inactive, so it gets filtered out.
SELECT meter_code, building_id, factor_id
FROM meters
WHERE status = 'Active';

-- name: 7.3 ORDER BY | Five biggest readings
-- note: LIMIT only keeps the output short. The top two are both the hostel grid meter.
SELECT reading_id, meter_id, reading_date, consumption_value
FROM energy_readings
ORDER BY consumption_value DESC
LIMIT 5;

-- name: 7.4 Aggregates | Summary of all readings
-- note: Units are mixed (kWh, L, kg) so the total is only a demo of the functions. Compare CO2e instead.
SELECT COUNT(*) AS total_readings,
       SUM(consumption_value) AS total_consumption,
       ROUND(AVG(consumption_value), 2) AS average_reading,
       MIN(consumption_value) AS minimum_reading,
       MAX(consumption_value) AS maximum_reading
FROM energy_readings;

-- name: 7.5 GROUP BY | Readings per meter
-- note: One row per meter instead of one row per reading.
SELECT meter_id, COUNT(*) AS reading_count,
       SUM(consumption_value) AS total_consumption
FROM energy_readings
GROUP BY meter_id;

-- name: 7.6 HAVING | Meters above 10,000 units
-- note: WHERE runs before grouping so it can't see SUM(). HAVING filters the groups afterwards.
SELECT meter_id, SUM(consumption_value) AS total_consumption
FROM energy_readings
GROUP BY meter_id
HAVING SUM(consumption_value) > 10000;

-- name: 7.6b HAVING + JOIN | Buildings over 5,000 kg CO2e
-- note: Library and Admin Block drop out (Admin only just, at 4,824 kg).
SELECT b.building_name,
       ROUND(SUM(er.consumption_value * ef.co2e_per_unit), 2) AS total_co2e_kg
FROM energy_readings er
JOIN meters m            ON er.meter_id = m.meter_id
JOIN buildings b         ON m.building_id = b.building_id
JOIN emission_factors ef ON m.factor_id = ef.factor_id
GROUP BY b.building_id, b.building_name
HAVING SUM(er.consumption_value * ef.co2e_per_unit) > 5000;

-- name: 7.7 JOIN | Readings with building and energy source
-- note: energy_readings only stores meter_id, so we go through meters to get the rest.
SELECT er.reading_id, b.building_name, m.meter_code,
       ef.source_type, er.consumption_value
FROM energy_readings er
JOIN meters m            ON er.meter_id = m.meter_id
JOIN buildings b         ON m.building_id = b.building_id
JOIN emission_factors ef ON m.factor_id = ef.factor_id
ORDER BY er.reading_id
LIMIT 6;

-- name: 7.7b JOIN | Initiatives next to their building
SELECT b.building_name, ai.title, ai.target_co2_reduction_kg, ai.status
FROM audit_initiatives ai
JOIN buildings b ON ai.building_id = b.building_id
ORDER BY ai.target_co2_reduction_kg DESC;

-- name: 7.8 JOIN + GROUP BY | CO2e per building
-- note: The main question of the project. Consumption x emission factor, summed per building.
SELECT b.building_name,
       ROUND(SUM(er.consumption_value * ef.co2e_per_unit), 2) AS total_co2e_kg
FROM energy_readings er
JOIN meters m            ON er.meter_id = m.meter_id
JOIN buildings b         ON m.building_id = b.building_id
JOIN emission_factors ef ON m.factor_id = ef.factor_id
GROUP BY b.building_id, b.building_name
ORDER BY total_co2e_kg DESC;

-- name: 7.8b JOIN + GROUP BY | CO2e per scope
-- note: Scope 2 (grid electricity) is about 77% of the 47,745.5 kg total.
SELECT ef.scope_level, COUNT(*) AS reading_count,
       SUM(er.consumption_value) AS total_consumption,
       ROUND(SUM(er.consumption_value * ef.co2e_per_unit), 2) AS total_co2e_kg
FROM energy_readings er
JOIN meters m            ON er.meter_id = m.meter_id
JOIN emission_factors ef ON m.factor_id = ef.factor_id
GROUP BY ef.scope_level
ORDER BY total_co2e_kg DESC;

-- name: 7.9 Subquery | Meters with a reading above the average
-- note: Inner query works out the average (3,553.33 on the sample data).
SELECT DISTINCT m.meter_code
FROM meters m
JOIN energy_readings er ON m.meter_id = er.meter_id
WHERE er.consumption_value >
      (SELECT AVG(consumption_value) FROM energy_readings);

-- name: 7.9b Subquery with IN | Buildings with an initiative In Progress
SELECT building_name, floors
FROM buildings
WHERE building_id IN (SELECT building_id
                      FROM audit_initiatives
                      WHERE status = 'In Progress');

-- name: 8.1 View | vw_building_carbon_summary
-- note: CO2e per sq ft makes buildings of different sizes comparable.
SELECT * FROM vw_building_carbon_summary
ORDER BY total_co2e_kg DESC;

-- name: 8.1b View + WHERE | Buildings above 0.1 kg CO2e / sq ft
SELECT building_name, co2e_per_sqft
FROM vw_building_carbon_summary
WHERE co2e_per_sqft > 0.1
ORDER BY co2e_per_sqft DESC;

-- name: 8.2 View | vw_scope_wise_emissions
SELECT * FROM vw_scope_wise_emissions
ORDER BY total_co2e_kg DESC;

-- name: R3 Trigger check | carbon_logs vs. a manual calculation
-- note: If the trigger is working, the two CO2e columns are always equal.
SELECT er.reading_id, er.consumption_value, ef.co2e_per_unit,
       ROUND(er.consumption_value * ef.co2e_per_unit, 3) AS expected_co2e,
       cl.calculated_co2e_kg AS logged_co2e
FROM energy_readings er
JOIN meters m            ON er.meter_id = m.meter_id
JOIN emission_factors ef ON m.factor_id = ef.factor_id
JOIN carbon_logs cl      ON cl.reading_id = er.reading_id
ORDER BY er.reading_id;

-- name: R3 Progress | Initiative targets vs. what the building emits now
-- note: LEFT JOIN so a building with an initiative but no readings yet still shows up.
SELECT ai.title, b.building_name, ai.status, ai.target_co2_reduction_kg,
       COALESCE(v.total_co2e_kg, 0) AS current_co2e_kg
FROM audit_initiatives ai
JOIN buildings b ON ai.building_id = b.building_id
LEFT JOIN vw_building_carbon_summary v ON v.building_id = b.building_id
ORDER BY ai.status, ai.target_co2_reduction_kg DESC;
