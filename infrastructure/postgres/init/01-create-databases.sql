-- Create all TMS service databases
CREATE DATABASE tms_gate;
CREATE DATABASE tms_bay;
CREATE DATABASE tms_schedule;
CREATE DATABASE tms_vendor;
CREATE DATABASE tms_notifications;
CREATE DATABASE tms_display;
CREATE DATABASE tms_auth;

-- Grant all privileges to the tms user
GRANT ALL PRIVILEGES ON DATABASE tms_gate TO tms;
GRANT ALL PRIVILEGES ON DATABASE tms_bay TO tms;
GRANT ALL PRIVILEGES ON DATABASE tms_schedule TO tms;
GRANT ALL PRIVILEGES ON DATABASE tms_vendor TO tms;
GRANT ALL PRIVILEGES ON DATABASE tms_notifications TO tms;
GRANT ALL PRIVILEGES ON DATABASE tms_display TO tms;
GRANT ALL PRIVILEGES ON DATABASE tms_auth TO tms;
