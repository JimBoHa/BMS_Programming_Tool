PROGRAM MAIN
VAR_INPUT
  StudioScanSeconds : REAL := 1.0;
  StudioDayOfWeek : INT := 0;
  StudioMinuteOfDay : INT := 0;
  n_value : REAL := 2.0;
  n_value_valid : BOOL := TRUE;
  n_request : BOOL := TRUE;
  n_request_valid : BOOL := TRUE;
  n_calendar_calendar : BOOL := FALSE;
  n_calendar_calendar_valid : BOOL := FALSE;
END_VAR
VAR_OUTPUT
  StudioFault : BOOL := FALSE;
  n_controller_out : REAL;
  n_memory_out : REAL;
  n_hysteresis_out : BOOL;
  n_timer_out : BOOL;
  n_alarm_out : BOOL;
  n_ramp_out : REAL;
  n_calendar_out : BOOL;
END_VAR
VAR
  n_setpoint : REAL;
  n_middle : REAL;
  n_controller : REAL;
  n_memory : REAL;
  n_hysteresis : BOOL;
  n_timer : BOOL;
  n_alarm : BOOL;
  n_ramp : REAL;
  n_calendar : BOOL;
  n_controller_out_stage : REAL;
  n_memory_out_stage : REAL;
  n_hysteresis_out_stage : BOOL;
  n_timer_out_stage : BOOL;
  n_alarm_out_stage : BOOL;
  n_ramp_out_stage : REAL;
  n_calendar_out_stage : BOOL;
  n_memory_memory : REAL := 7.25;
  n_alarm_elapsed : REAL := 0.0;
  n_alarm_next : REAL := 0.0;
  n_controller_integral : REAL := 0.0;
  n_controller_candidate : REAL := 0.0;
  n_controller_error : REAL := 0.0;
  n_controller_raw : REAL := 0.0;
  n_hysteresis_memory : BOOL := TRUE;
  n_ramp_memory : REAL := 3.0;
  n_timer_elapsed : REAL := 0.0;
  n_timer_next : REAL := 0.0;
END_VAR
(* BMS Studio scan. Inputs and clock are supplied by the target runtime. *)
StudioFault := FALSE;
IF (StudioScanSeconds <= 0.0) OR (StudioScanSeconds > 60.0) THEN StudioFault := TRUE; RETURN; END_IF;
IF NOT n_value_valid OR (n_value <> n_value) OR (ABS(n_value) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
IF NOT n_request_valid THEN StudioFault := TRUE; RETURN; END_IF;
IF NOT n_calendar_calendar_valid THEN StudioFault := TRUE; RETURN; END_IF;
(* Host evaluates the project's IANA timezone and dated exceptions; mark valid only for the current scan. *)
n_calendar := n_calendar_calendar;
n_memory := n_memory_memory;
IF (n_memory <> n_memory) OR (ABS(n_memory) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_middle := 0.5;
IF (n_middle <> n_middle) OR (ABS(n_middle) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_setpoint := 5.0;
IF (n_setpoint <> n_setpoint) OR (ABS(n_setpoint) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
IF n_value > 4.0 THEN n_alarm_next := n_alarm_elapsed + StudioScanSeconds; ELSE n_alarm_next := 0.0; END_IF;
n_alarm := (n_value > 4.0) AND (n_alarm_next >= 2.0);
n_calendar_out_stage := n_calendar;
n_controller_error := (n_setpoint - n_value) * 1.0;
n_controller_candidate := n_controller_integral + 0.5 * n_controller_error * StudioScanSeconds;
n_controller_raw := 2.0 * n_controller_error + n_controller_candidate;
IF ((n_controller_raw >= -100.0) AND (n_controller_raw <= 100.0)) OR ((n_controller_raw > 100.0) AND (n_controller_error * 0.5 < 0.0)) OR ((n_controller_raw < -100.0) AND (n_controller_error * 0.5 > 0.0)) THEN
  n_controller := MAX(-100.0, MIN(100.0, 2.0 * n_controller_error + n_controller_candidate));
ELSE
  n_controller_candidate := n_controller_integral;
  n_controller := MAX(-100.0, MIN(100.0, 2.0 * n_controller_error + n_controller_integral));
END_IF;
IF (n_controller <> n_controller) OR (ABS(n_controller) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_hysteresis := n_hysteresis_memory;
IF n_middle >= 1.0 THEN n_hysteresis := TRUE; ELSIF n_middle <= 0.0 THEN n_hysteresis := FALSE; END_IF;
n_memory_out_stage := n_memory;
IF (n_memory_out_stage <> n_memory_out_stage) OR (ABS(n_memory_out_stage) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_ramp := n_ramp_memory + MAX(-(1.0 * StudioScanSeconds), MIN(1.0 * StudioScanSeconds, n_setpoint - n_ramp_memory));
IF (n_ramp <> n_ramp) OR (ABS(n_ramp) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
IF n_request THEN n_timer_next := n_timer_elapsed + StudioScanSeconds; ELSE n_timer_next := 0.0; END_IF;
n_timer := (n_request) AND (n_timer_next >= 2.0);
n_alarm_out_stage := n_alarm;
n_controller_out_stage := n_controller;
IF (n_controller_out_stage <> n_controller_out_stage) OR (ABS(n_controller_out_stage) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_hysteresis_out_stage := n_hysteresis;
n_ramp_out_stage := n_ramp;
IF (n_ramp_out_stage <> n_ramp_out_stage) OR (ABS(n_ramp_out_stage) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_timer_out_stage := n_timer;
(* Commit state and outputs only after every block succeeds. *)
n_memory_memory := n_value;
n_alarm_elapsed := n_alarm_next;
n_controller_integral := n_controller_candidate;
n_hysteresis_memory := n_hysteresis;
n_ramp_memory := n_ramp;
n_timer_elapsed := n_timer_next;
n_calendar_out := n_calendar_out_stage;
n_memory_out := n_memory_out_stage;
n_alarm_out := n_alarm_out_stage;
n_controller_out := n_controller_out_stage;
n_hysteresis_out := n_hysteresis_out_stage;
n_ramp_out := n_ramp_out_stage;
n_timer_out := n_timer_out_stage;
END_PROGRAM
(* BMS_STUDIO_IR_V2 eyJwcm9ncmFtIjp7ImRlc2NyaXB0aW9uIjoiIiwiZWRnZXMiOlt7ImlkIjoiZWRnZTAiLCJzb3VyY2UiOiJzZXRwb2ludCIsInNvdXJjZV9wb3J0Ijoib3V0IiwidGFyZ2V0IjoiY29udHJvbGxlciIsInRhcmdldF9wb3J0Ijoic2V0cG9pbnQifSx7ImlkIjoiZWRnZTEiLCJzb3VyY2UiOiJ2YWx1ZSIsInNvdXJjZV9wb3J0Ijoib3V0IiwidGFyZ2V0IjoiY29udHJvbGxlciIsInRhcmdldF9wb3J0IjoibWVhc3VyZWQifSx7ImlkIjoiZWRnZTIiLCJzb3VyY2UiOiJ2YWx1ZSIsInNvdXJjZV9wb3J0Ijoib3V0IiwidGFyZ2V0IjoibWVtb3J5IiwidGFyZ2V0X3BvcnQiOiJpbiJ9LHsiaWQiOiJlZGdlMyIsInNvdXJjZSI6Im1pZGRsZSIsInNvdXJjZV9wb3J0Ijoib3V0IiwidGFyZ2V0IjoiaHlzdGVyZXNpcyIsInRhcmdldF9wb3J0IjoiaW4ifSx7ImlkIjoiZWRnZTQiLCJzb3VyY2UiOiJyZXF1ZXN0Iiwic291cmNlX3BvcnQiOiJvdXQiLCJ0YXJnZXQiOiJ0aW1lciIsInRhcmdldF9wb3J0IjoiaW4ifSx7ImlkIjoiZWRnZTUiLCJzb3VyY2UiOiJ2YWx1ZSIsInNvdXJjZV9wb3J0Ijoib3V0IiwidGFyZ2V0IjoiYWxhcm0iLCJ0YXJnZXRfcG9ydCI6ImluIn0seyJpZCI6ImVkZ2U2Iiwic291cmNlIjoic2V0cG9pbnQiLCJzb3VyY2VfcG9ydCI6Im91dCIsInRhcmdldCI6InJhbXAiLCJ0YXJnZXRfcG9ydCI6ImluIn0seyJpZCI6ImVkZ2U3Iiwic291cmNlIjoiY29udHJvbGxlciIsInNvdXJjZV9wb3J0Ijoib3V0IiwidGFyZ2V0IjoiY29udHJvbGxlcl9vdXQiLCJ0YXJnZXRfcG9ydCI6ImluIn0seyJpZCI6ImVkZ2U4Iiwic291cmNlIjoibWVtb3J5Iiwic291cmNlX3BvcnQiOiJvdXQiLCJ0YXJnZXQiOiJtZW1vcnlfb3V0IiwidGFyZ2V0X3BvcnQiOiJpbiJ9LHsiaWQiOiJlZGdlOSIsInNvdXJjZSI6Imh5c3RlcmVzaXMiLCJzb3VyY2VfcG9ydCI6Im91dCIsInRhcmdldCI6Imh5c3RlcmVzaXNfb3V0IiwidGFyZ2V0X3BvcnQiOiJpbiJ9LHsiaWQiOiJlZGdlMTAiLCJzb3VyY2UiOiJ0aW1lciIsInNvdXJjZV9wb3J0Ijoib3V0IiwidGFyZ2V0IjoidGltZXJfb3V0IiwidGFyZ2V0X3BvcnQiOiJpbiJ9LHsiaWQiOiJlZGdlMTEiLCJzb3VyY2UiOiJhbGFybSIsInNvdXJjZV9wb3J0Ijoib3V0IiwidGFyZ2V0IjoiYWxhcm1fb3V0IiwidGFyZ2V0X3BvcnQiOiJpbiJ9LHsiaWQiOiJlZGdlMTIiLCJzb3VyY2UiOiJyYW1wIiwic291cmNlX3BvcnQiOiJvdXQiLCJ0YXJnZXQiOiJyYW1wX291dCIsInRhcmdldF9wb3J0IjoiaW4ifSx7ImlkIjoiZWRnZTEzIiwic291cmNlIjoiY2FsZW5kYXIiLCJzb3VyY2VfcG9ydCI6Im91dCIsInRhcmdldCI6ImNhbGVuZGFyX291dCIsInRhcmdldF9wb3J0IjoiaW4ifV0sImlkIjoic3RhdGUtY2FsZW5kYXIiLCJtZXRhZGF0YSI6e30sIm5hbWUiOiJzdGF0ZS1jYWxlbmRhciIsIm5vZGVzIjpbeyJpZCI6InZhbHVlIiwia2luZCI6IklucHV0IiwibGFiZWwiOiIiLCJwYXJhbXMiOnsiZGVmYXVsdCI6Mn0sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoibnVtYmVyIiwieCI6MC4wLCJ5IjowLjB9LHsiaWQiOiJyZXF1ZXN0Iiwia2luZCI6IklucHV0IiwibGFiZWwiOiIiLCJwYXJhbXMiOnsiZGVmYXVsdCI6dHJ1ZX0sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoiYm9vbGVhbiIsIngiOjAuMCwieSI6MC4wfSx7ImlkIjoic2V0cG9pbnQiLCJraW5kIjoiQ29uc3RhbnQiLCJsYWJlbCI6IiIsInBhcmFtcyI6eyJ2YWx1ZSI6NX0sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoibnVtYmVyIiwieCI6MC4wLCJ5IjowLjB9LHsiaWQiOiJtaWRkbGUiLCJraW5kIjoiQ29uc3RhbnQiLCJsYWJlbCI6IiIsInBhcmFtcyI6eyJ2YWx1ZSI6MC41fSwidW5pdCI6IiIsInZhbHVlX3R5cGUiOiJudW1iZXIiLCJ4IjowLjAsInkiOjAuMH0seyJpZCI6ImNvbnRyb2xsZXIiLCJraW5kIjoiUEkiLCJsYWJlbCI6IiIsInBhcmFtcyI6eyJraSI6MC41LCJrcCI6MiwibWF4IjoxMDAsIm1pbiI6LTEwMH0sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoibnVtYmVyIiwieCI6MC4wLCJ5IjowLjB9LHsiaWQiOiJtZW1vcnkiLCJraW5kIjoiRGVsYXkiLCJsYWJlbCI6IiIsInBhcmFtcyI6eyJpbml0aWFsIjo3LjI1fSwidW5pdCI6IiIsInZhbHVlX3R5cGUiOiJudW1iZXIiLCJ4IjowLjAsInkiOjAuMH0seyJpZCI6Imh5c3RlcmVzaXMiLCJraW5kIjoiRGVhZGJhbmQiLCJsYWJlbCI6IiIsInBhcmFtcyI6eyJpbml0aWFsIjp0cnVlLCJvZmYiOjAsIm9uIjoxfSwidW5pdCI6IiIsInZhbHVlX3R5cGUiOiJib29sZWFuIiwieCI6MC4wLCJ5IjowLjB9LHsiaWQiOiJ0aW1lciIsImtpbmQiOiJUaW1lck9uIiwibGFiZWwiOiIiLCJwYXJhbXMiOnsic2Vjb25kcyI6Mn0sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoiYm9vbGVhbiIsIngiOjAuMCwieSI6MC4wfSx7ImlkIjoiYWxhcm0iLCJraW5kIjoiQWxhcm0iLCJsYWJlbCI6IiIsInBhcmFtcyI6eyJkZWxheSI6MiwibGltaXQiOjR9LCJ1bml0IjoiIiwidmFsdWVfdHlwZSI6ImJvb2xlYW4iLCJ4IjowLjAsInkiOjAuMH0seyJpZCI6InJhbXAiLCJraW5kIjoiU2xldyIsImxhYmVsIjoiIiwicGFyYW1zIjp7ImluaXRpYWwiOjMsInJhdGUiOjF9LCJ1bml0IjoiIiwidmFsdWVfdHlwZSI6Im51bWJlciIsIngiOjAuMCwieSI6MC4wfSx7ImlkIjoiY2FsZW5kYXIiLCJraW5kIjoiU2NoZWR1bGUiLCJsYWJlbCI6IiIsInBhcmFtcyI6eyJleGNlcHRpb25zIjpbeyJkYXRlIjoiMjAyNi0wMS0wNSIsImVuYWJsZWQiOnRydWUsImVuZCI6IjIzOjU5Iiwic3RhcnQiOiIwMDowMCJ9XSwidGltZXpvbmUiOiJBbWVyaWNhL0xvc19BbmdlbGVzIn0sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoiYm9vbGVhbiIsIngiOjAuMCwieSI6MC4wfSx7ImlkIjoiY29udHJvbGxlcl9vdXQiLCJraW5kIjoiT3V0cHV0IiwibGFiZWwiOiIiLCJwYXJhbXMiOnt9LCJ1bml0IjoiIiwidmFsdWVfdHlwZSI6Im51bWJlciIsIngiOjAuMCwieSI6MC4wfSx7ImlkIjoibWVtb3J5X291dCIsImtpbmQiOiJPdXRwdXQiLCJsYWJlbCI6IiIsInBhcmFtcyI6e30sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoibnVtYmVyIiwieCI6MC4wLCJ5IjowLjB9LHsiaWQiOiJoeXN0ZXJlc2lzX291dCIsImtpbmQiOiJPdXRwdXQiLCJsYWJlbCI6IiIsInBhcmFtcyI6e30sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoiYm9vbGVhbiIsIngiOjAuMCwieSI6MC4wfSx7ImlkIjoidGltZXJfb3V0Iiwia2luZCI6Ik91dHB1dCIsImxhYmVsIjoiIiwicGFyYW1zIjp7fSwidW5pdCI6IiIsInZhbHVlX3R5cGUiOiJib29sZWFuIiwieCI6MC4wLCJ5IjowLjB9LHsiaWQiOiJhbGFybV9vdXQiLCJraW5kIjoiT3V0cHV0IiwibGFiZWwiOiIiLCJwYXJhbXMiOnt9LCJ1bml0IjoiIiwidmFsdWVfdHlwZSI6ImJvb2xlYW4iLCJ4IjowLjAsInkiOjAuMH0seyJpZCI6InJhbXBfb3V0Iiwia2luZCI6Ik91dHB1dCIsImxhYmVsIjoiIiwicGFyYW1zIjp7fSwidW5pdCI6IiIsInZhbHVlX3R5cGUiOiJudW1iZXIiLCJ4IjowLjAsInkiOjAuMH0seyJpZCI6ImNhbGVuZGFyX291dCIsImtpbmQiOiJPdXRwdXQiLCJsYWJlbCI6IiIsInBhcmFtcyI6e30sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoiYm9vbGVhbiIsIngiOjAuMCwieSI6MC4wfV0sInJldmlzaW9uIjowLCJzY2FuX3NlY29uZHMiOjEuMCwic2NoZW1hX3ZlcnNpb24iOjEsInRhcmdldCI6eyJmYW1pbHkiOiJ1bml2ZXJzYWwtcnVudGltZSIsImZpcm13YXJlIjoiIiwibWF4X25vZGVzIjoyMDAwLCJtb2RlbCI6IiIsInBoeXNpY2FsX2lucHV0cyI6bnVsbCwicGh5c2ljYWxfb3V0cHV0cyI6bnVsbCwicmVsZWFzZV9tb2RlIjoiIn19LCJzb3VyY2VfZ2VuZXJhdG9yIjp7ImlkIjoic3R1ZGlvLWxpdGVyYWxzLzIiLCJydWxlc19zaGEyNTYiOiJiZTAxNGNhNTFjMWQzZTQyNTM4ZDYwN2Q2OThiOGRkYWNkMTY0YjJlMGRkZmI4MjFjNDMzMzI5Yjk5MDUwNDkzIn19 *)
