-- Green Campus Carbon Footprint & Energy Audit Tracker
-- Final schema (Review 3)
--
-- Same seven tables as Review 2. What's new for Review 3:
--   * trg_after_energy_reading_update  -> keeps carbon_logs right when a reading is edited
--   * sp_GetCampusAuditReport          -> date-range audit report used by the app
--
-- Run this first, then 02_seed.sql. Safe to re-run, it drops and recreates everything.

CREATE DATABASE IF NOT EXISTS green_campus_db;
USE green_campus_db;

DROP VIEW IF EXISTS vw_scope_wise_emissions;
DROP VIEW IF EXISTS vw_building_carbon_summary;
DROP PROCEDURE IF EXISTS sp_GetCampusAuditReport;
DROP TRIGGER IF EXISTS trg_after_energy_reading_insert;
DROP TRIGGER IF EXISTS trg_after_energy_reading_update;

DROP TABLE IF EXISTS carbon_logs;
DROP TABLE IF EXISTS energy_readings;
DROP TABLE IF EXISTS audit_initiatives;
DROP TABLE IF EXISTS meters;
DROP TABLE IF EXISTS emission_factors;
DROP TABLE IF EXISTS buildings;
DROP TABLE IF EXISTS departments;


CREATE TABLE departments (
    dept_id           INT PRIMARY KEY AUTO_INCREMENT,
    dept_name         VARCHAR(100) NOT NULL UNIQUE,
    head_of_dept      VARCHAR(100) NOT NULL,
    budget_allocated  DECIMAL(12,2) NOT NULL CHECK (budget_allocated >= 0),
    contact_emails    VARCHAR(255) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE buildings (
    building_id      INT PRIMARY KEY,
    building_name    VARCHAR(120) NOT NULL UNIQUE,
    dept_id          INT NULL,
    floors           INT NOT NULL CHECK (floors > 0),
    total_area_sqft  DECIMAL(12,2) NOT NULL CHECK (total_area_sqft > 0),
    CONSTRAINT fk_building_department
        FOREIGN KEY (dept_id) REFERENCES departments(dept_id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE emission_factors (
    factor_id      INT PRIMARY KEY,
    source_type    VARCHAR(80) NOT NULL UNIQUE,
    unit           VARCHAR(20) NOT NULL,
    co2e_per_unit  DECIMAL(10,4) NOT NULL CHECK (co2e_per_unit >= 0),
    scope_level    ENUM('Scope 1','Scope 2','Scope 3') NOT NULL
) ENGINE=InnoDB;

CREATE TABLE meters (
    meter_id     INT PRIMARY KEY,
    meter_code   VARCHAR(50) NOT NULL UNIQUE,
    building_id  INT NOT NULL,
    factor_id    INT NOT NULL,
    status       ENUM('Active','Inactive','Maintenance') NOT NULL DEFAULT 'Active',
    CONSTRAINT fk_meter_building
        FOREIGN KEY (building_id) REFERENCES buildings(building_id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_meter_factor
        FOREIGN KEY (factor_id) REFERENCES emission_factors(factor_id)
        ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE energy_readings (
    reading_id         INT PRIMARY KEY,
    meter_id           INT NOT NULL,
    reading_date       DATE NOT NULL,
    consumption_value  DECIMAL(12,3) NOT NULL CHECK (consumption_value >= 0),
    cost_incurred      DECIMAL(12,2) NOT NULL CHECK (cost_incurred >= 0),
    CONSTRAINT fk_reading_meter
        FOREIGN KEY (meter_id) REFERENCES meters(meter_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE carbon_logs (
    log_id              INT PRIMARY KEY AUTO_INCREMENT,
    reading_id          INT NOT NULL UNIQUE,
    calculated_co2e_kg  DECIMAL(14,3) NOT NULL CHECK (calculated_co2e_kg >= 0),
    logged_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_carbon_reading
        FOREIGN KEY (reading_id) REFERENCES energy_readings(reading_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE audit_initiatives (
    initiative_id            INT PRIMARY KEY,
    building_id              INT NOT NULL,
    title                    VARCHAR(160) NOT NULL,
    target_co2_reduction_kg  DECIMAL(14,2) NOT NULL CHECK (target_co2_reduction_kg >= 0),
    status                   ENUM('Proposed','In Progress','Completed') NOT NULL,
    CONSTRAINT fk_initiative_building
        FOREIGN KEY (building_id) REFERENCES buildings(building_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;


-- ---------------------------------------------------------------
-- Triggers
-- ---------------------------------------------------------------
DELIMITER //

-- from Review 2: every new reading gets its carbon log automatically
CREATE TRIGGER trg_after_energy_reading_insert
AFTER INSERT ON energy_readings
FOR EACH ROW
BEGIN
    DECLARE factor_rate DECIMAL(10,4);

    SELECT ef.co2e_per_unit INTO factor_rate
    FROM meters m
    JOIN emission_factors ef ON m.factor_id = ef.factor_id
    WHERE m.meter_id = NEW.meter_id;

    INSERT INTO carbon_logs (reading_id, calculated_co2e_kg)
    VALUES (NEW.reading_id, NEW.consumption_value * factor_rate);
END//

-- new in Review 3: once the app could edit readings, the old log value went stale.
-- Only recalculated when the reading itself changes (value or meter). A change to an
-- emission factor does NOT touch old logs, that's the audit-record point from Review 2.
CREATE TRIGGER trg_after_energy_reading_update
AFTER UPDATE ON energy_readings
FOR EACH ROW
BEGIN
    DECLARE factor_rate DECIMAL(10,4);

    IF NEW.consumption_value <> OLD.consumption_value OR NEW.meter_id <> OLD.meter_id THEN
        SELECT ef.co2e_per_unit INTO factor_rate
        FROM meters m
        JOIN emission_factors ef ON m.factor_id = ef.factor_id
        WHERE m.meter_id = NEW.meter_id;

        UPDATE carbon_logs
        SET calculated_co2e_kg = NEW.consumption_value * factor_rate,
            logged_at = CURRENT_TIMESTAMP
        WHERE reading_id = NEW.reading_id;
    END IF;
END//


-- ---------------------------------------------------------------
-- Stored procedure: audit report for a date range
-- (this is the sp_GetCampusAuditReport we showed in the Review 1 slides)
-- ---------------------------------------------------------------
CREATE PROCEDURE sp_GetCampusAuditReport(IN p_from DATE, IN p_to DATE)
BEGIN
    SELECT b.building_name,
           ef.scope_level,
           ef.source_type,
           COUNT(er.reading_id)              AS readings,
           SUM(er.consumption_value)         AS period_consumption,
           ef.unit,
           ROUND(SUM(cl.calculated_co2e_kg), 2) AS period_co2e_kg,
           SUM(er.cost_incurred)             AS period_cost
    FROM energy_readings er
    JOIN meters m            ON er.meter_id = m.meter_id
    JOIN buildings b         ON m.building_id = b.building_id
    JOIN emission_factors ef ON m.factor_id = ef.factor_id
    JOIN carbon_logs cl      ON cl.reading_id = er.reading_id
    WHERE er.reading_date BETWEEN p_from AND p_to
    GROUP BY b.building_id, b.building_name, ef.scope_level, ef.source_type, ef.unit
    ORDER BY period_co2e_kg DESC;
END//

DELIMITER ;


-- ---------------------------------------------------------------
-- Views (same as Review 2, section 8)
-- ---------------------------------------------------------------
CREATE OR REPLACE VIEW vw_building_carbon_summary AS
SELECT b.building_id, b.building_name, b.total_area_sqft,
       SUM(er.consumption_value) AS total_consumption,
       ROUND(SUM(er.consumption_value * ef.co2e_per_unit), 2) AS total_co2e_kg,
       ROUND(SUM(er.consumption_value * ef.co2e_per_unit) / b.total_area_sqft, 4) AS co2e_per_sqft
FROM buildings b
JOIN meters m            ON b.building_id = m.building_id
JOIN energy_readings er  ON m.meter_id = er.meter_id
JOIN emission_factors ef ON m.factor_id = ef.factor_id
GROUP BY b.building_id, b.building_name, b.total_area_sqft;

CREATE OR REPLACE VIEW vw_scope_wise_emissions AS
SELECT ef.scope_level, COUNT(*) AS reading_count,
       SUM(er.consumption_value) AS total_consumption,
       ROUND(SUM(er.consumption_value * ef.co2e_per_unit), 2) AS total_co2e_kg
FROM energy_readings er
JOIN meters m            ON er.meter_id = m.meter_id
JOIN emission_factors ef ON m.factor_id = ef.factor_id
GROUP BY ef.scope_level;
