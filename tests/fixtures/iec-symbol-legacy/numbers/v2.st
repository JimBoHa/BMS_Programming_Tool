PROGRAM MAIN
VAR_INPUT
  StudioScanSeconds : REAL := 1.0;
  StudioDayOfWeek : INT := 0;
  StudioMinuteOfDay : INT := 0;
  n_source : REAL := 1.000000059604645;
  n_source_valid : BOOL := TRUE;
END_VAR
VAR_OUTPUT
  StudioFault : BOOL := FALSE;
  n_output_value : REAL;
  n_output_zero : REAL;
  n_output_large : REAL;
END_VAR
VAR
  n_negative_zero : REAL;
  n_large_even_integer : REAL;
  n_output_value_stage : REAL;
  n_output_zero_stage : REAL;
  n_output_large_stage : REAL;
END_VAR
(* BMS Studio scan. Inputs and clock are supplied by the target runtime. *)
StudioFault := FALSE;
IF (StudioScanSeconds <= 0.0) OR (StudioScanSeconds > 60.0) THEN StudioFault := TRUE; RETURN; END_IF;
IF NOT n_source_valid OR (n_source <> n_source) OR (ABS(n_source) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_large_even_integer := 1152921504606846976.0;
IF (n_large_even_integer <> n_large_even_integer) OR (ABS(n_large_even_integer) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_negative_zero := -0.0;
IF (n_negative_zero <> n_negative_zero) OR (ABS(n_negative_zero) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_output_large_stage := n_large_even_integer;
IF (n_output_large_stage <> n_output_large_stage) OR (ABS(n_output_large_stage) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_output_value_stage := n_source;
IF (n_output_value_stage <> n_output_value_stage) OR (ABS(n_output_value_stage) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_output_zero_stage := n_negative_zero;
IF (n_output_zero_stage <> n_output_zero_stage) OR (ABS(n_output_zero_stage) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
(* Commit state and outputs only after every block succeeds. *)
n_output_large := n_output_large_stage;
n_output_value := n_output_value_stage;
n_output_zero := n_output_zero_stage;
END_PROGRAM
(* BMS_STUDIO_IR_V2 eyJwcm9ncmFtIjp7ImRlc2NyaXB0aW9uIjoiIiwiZWRnZXMiOlt7ImlkIjoiZWRnZTAiLCJzb3VyY2UiOiJzb3VyY2UiLCJzb3VyY2VfcG9ydCI6Im91dCIsInRhcmdldCI6Im91dHB1dF92YWx1ZSIsInRhcmdldF9wb3J0IjoiaW4ifSx7ImlkIjoiZWRnZTEiLCJzb3VyY2UiOiJuZWdhdGl2ZV96ZXJvIiwic291cmNlX3BvcnQiOiJvdXQiLCJ0YXJnZXQiOiJvdXRwdXRfemVybyIsInRhcmdldF9wb3J0IjoiaW4ifSx7ImlkIjoiZWRnZTIiLCJzb3VyY2UiOiJsYXJnZV9ldmVuX2ludGVnZXIiLCJzb3VyY2VfcG9ydCI6Im91dCIsInRhcmdldCI6Im91dHB1dF9sYXJnZSIsInRhcmdldF9wb3J0IjoiaW4ifV0sImlkIjoibnVtYmVycyIsIm1ldGFkYXRhIjp7Im9wYXF1ZSI6eyJzaWduZWRfemVybyI6LTAuMCwidmVuZG9yX251bWJlciI6MWUrMzB9fSwibmFtZSI6Im51bWJlcnMiLCJub2RlcyI6W3siaWQiOiJzb3VyY2UiLCJraW5kIjoiSW5wdXQiLCJsYWJlbCI6IiIsInBhcmFtcyI6eyJkZWZhdWx0IjoxLjAwMDAwMDA1OTYwNDY0NX0sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoibnVtYmVyIiwieCI6MC4wLCJ5IjowLjB9LHsiaWQiOiJuZWdhdGl2ZV96ZXJvIiwia2luZCI6IkNvbnN0YW50IiwibGFiZWwiOiIiLCJwYXJhbXMiOnsidmFsdWUiOi0wLjB9LCJ1bml0IjoiIiwidmFsdWVfdHlwZSI6Im51bWJlciIsIngiOjAuMCwieSI6MC4wfSx7ImlkIjoibGFyZ2VfZXZlbl9pbnRlZ2VyIiwia2luZCI6IkNvbnN0YW50IiwibGFiZWwiOiIiLCJwYXJhbXMiOnsidmFsdWUiOjExNTI5MjE1MDQ2MDY4NDY5NzZ9LCJ1bml0IjoiIiwidmFsdWVfdHlwZSI6Im51bWJlciIsIngiOjAuMCwieSI6MC4wfSx7ImlkIjoib3V0cHV0X3ZhbHVlIiwia2luZCI6Ik91dHB1dCIsImxhYmVsIjoiIiwicGFyYW1zIjp7fSwidW5pdCI6IiIsInZhbHVlX3R5cGUiOiJudW1iZXIiLCJ4IjowLjAsInkiOjAuMH0seyJpZCI6Im91dHB1dF96ZXJvIiwia2luZCI6Ik91dHB1dCIsImxhYmVsIjoiIiwicGFyYW1zIjp7fSwidW5pdCI6IiIsInZhbHVlX3R5cGUiOiJudW1iZXIiLCJ4IjowLjAsInkiOjAuMH0seyJpZCI6Im91dHB1dF9sYXJnZSIsImtpbmQiOiJPdXRwdXQiLCJsYWJlbCI6IiIsInBhcmFtcyI6e30sInVuaXQiOiIiLCJ2YWx1ZV90eXBlIjoibnVtYmVyIiwieCI6MC4wLCJ5IjowLjB9XSwicmV2aXNpb24iOjAsInNjYW5fc2Vjb25kcyI6MS4wLCJzY2hlbWFfdmVyc2lvbiI6MSwidGFyZ2V0Ijp7ImZhbWlseSI6InVuaXZlcnNhbC1ydW50aW1lIiwiZmlybXdhcmUiOiIiLCJtYXhfbm9kZXMiOjIwMDAsIm1vZGVsIjoiIiwicGh5c2ljYWxfaW5wdXRzIjpudWxsLCJwaHlzaWNhbF9vdXRwdXRzIjpudWxsLCJyZWxlYXNlX21vZGUiOiIifX0sInNvdXJjZV9nZW5lcmF0b3IiOnsiaWQiOiJzdHVkaW8tbGl0ZXJhbHMvMiIsInJ1bGVzX3NoYTI1NiI6ImJlMDE0Y2E1MWMxZDNlNDI1MzhkNjA3ZDY5OGI4ZGRhY2QxNjRiMmUwZGRmYjgyMWM0MzMzMjliOTkwNTA0OTMifX0= *)
