-- Sample data. Identical to Review 2 so all the outputs in that report still match.
-- carbon_logs is never inserted into directly, the trigger fills it.

USE green_campus_db;

INSERT INTO departments (dept_id, dept_name, head_of_dept, budget_allocated, contact_emails) VALUES
(1, 'Computer Science & Engineering', 'Dr. Ananya Rao',   12500000.00, 'cse@greenuniv.edu'),
(2, 'Mechanical Engineering',         'Dr. Vikram Menon',  9800000.00, 'mech@greenuniv.edu'),
(3, 'Campus Facilities',              'Ms. Priya Nair',   15000000.00, 'facilities@greenuniv.edu');

INSERT INTO buildings (building_id, building_name, dept_id, floors, total_area_sqft) VALUES
(101, 'Main Academic Block',  1, 5,  85000),
(102, 'CSE Research Center',  1, 4,  62000),
(103, 'Mechanical Workshop',  2, 3,  54000),
(104, 'Central Library',      3, 4,  70000),
(105, 'Hostel Block A',       3, 6, 110000),
(106, 'Administration Block', 3, 3,  42000);

INSERT INTO emission_factors (factor_id, source_type, unit, co2e_per_unit, scope_level) VALUES
(1, 'Diesel',              'L',   2.6800, 'Scope 1'),
(2, 'Grid Electricity',    'kWh', 0.8200, 'Scope 2'),
(3, 'Solar Electricity',   'kWh', 0.0500, 'Scope 2'),
(4, 'LPG',                 'kg',  3.0000, 'Scope 1'),
(5, 'Purchased Steam',     'kWh', 0.2500, 'Scope 3'),
(6, 'Refrigerant Leakage', 'kg',  1.4300, 'Scope 3');

INSERT INTO meters (meter_id, meter_code, building_id, factor_id, status) VALUES
(1001, 'ELEC-MAB-01',  101, 2, 'Active'),
(1002, 'ELEC-CRC-01',  102, 2, 'Active'),
(1003, 'DG-MW-01',     103, 1, 'Active'),
(1004, 'ELEC-CL-01',   104, 2, 'Active'),
(1005, 'ELEC-HSA-01',  105, 2, 'Active'),
(1006, 'SOLAR-HSA-01', 105, 3, 'Active'),
(1007, 'DG-FAC-01',    106, 1, 'Active'),
(1008, 'STEAM-CL-01',  104, 5, 'Inactive');

INSERT INTO energy_readings (reading_id, meter_id, reading_date, consumption_value, cost_incurred) VALUES
(2001, 1001, '2026-09-01', 5200,  728.00),
(2002, 1001, '2026-09-02', 5100,  714.00),
(2003, 1001, '2026-09-03', 5300,  742.00),
(2004, 1002, '2026-09-01', 4100,  574.00),
(2005, 1002, '2026-09-02', 4300,  602.00),
(2006, 1003, '2026-09-01', 1200, 1080.00),
(2007, 1003, '2026-09-02',  950,  855.00),
(2008, 1004, '2026-09-01', 3500,  490.00),
(2009, 1005, '2026-09-01', 6200,  868.00),
(2010, 1005, '2026-09-02', 6400,  896.00),
(2011, 1006, '2026-09-01', 3000,  120.00),
(2012, 1007, '2026-09-01', 1800, 1620.00),
(2013, 1008, '2026-09-01',  900,  135.00),
(2014, 1008, '2026-09-02',  850,  127.50),
(2015, 1002, '2026-09-03', 4500,  630.00);

INSERT INTO audit_initiatives (initiative_id, building_id, title, target_co2_reduction_kg, status) VALUES
(3001, 101, 'LED Retrofit - Main Academic Block', 12000, 'In Progress'),
(3002, 102, 'Server Room Cooling Optimization',    8000, 'Proposed'),
(3003, 104, 'Library HVAC Efficiency Program',    10000, 'Completed'),
(3004, 105, 'Hostel Solar Expansion',             18000, 'In Progress'),
(3005, 106, 'Diesel Generator Efficiency Audit',   6000, 'Proposed');
