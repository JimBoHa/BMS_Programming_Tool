PROGRAM MAIN
VAR_INPUT
  StudioScanSeconds : REAL := 1.0;
  StudioDayOfWeek : INT := 0;
  StudioMinuteOfDay : INT := 0;
END_VAR
VAR_OUTPUT
  StudioFault : BOOL := FALSE;
  n_out : REAL;
END_VAR
VAR
  n_source : REAL;
  n_out_stage : REAL;
END_VAR
(* BMS Studio scan. Inputs and clock are supplied by the target runtime. *)
StudioFault := FALSE;
IF (StudioScanSeconds <= 0.0) OR (StudioScanSeconds > 60.0) THEN StudioFault := TRUE; RETURN; END_IF;
n_source := 1.00000005960464;
IF (n_source <> n_source) OR (ABS(n_source) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
n_out_stage := n_source;
IF (n_out_stage <> n_out_stage) OR (ABS(n_out_stage) > 3.0E+38) THEN StudioFault := TRUE; RETURN; END_IF;
(* Commit state and outputs only after every block succeeds. *)
n_out := n_out_stage;
END_PROGRAM
(* BMS_STUDIO_IR_V1 ewogICJkZXNjcmlwdGlvbiI6ICIiLAogICJlZGdlcyI6IFsKICAgIHsKICAgICAgImlkIjogIndpcmUiLAogICAgICAic291cmNlIjogInNvdXJjZSIsCiAgICAgICJzb3VyY2VfcG9ydCI6ICJvdXQiLAogICAgICAidGFyZ2V0IjogIm91dCIsCiAgICAgICJ0YXJnZXRfcG9ydCI6ICJpbiIKICAgIH0KICBdLAogICJpZCI6ICJsZWdhY3ktbGl0ZXJhbC1zYWZlIiwKICAibWV0YWRhdGEiOiB7fSwKICAibmFtZSI6ICJTeW50aGV0aWMgbGVnYWN5IHNhZmUgbGl0ZXJhbCBhcmNoaXZlIiwKICAibm9kZXMiOiBbCiAgICB7CiAgICAgICJpZCI6ICJzb3VyY2UiLAogICAgICAia2luZCI6ICJDb25zdGFudCIsCiAgICAgICJsYWJlbCI6ICIiLAogICAgICAicGFyYW1zIjogewogICAgICAgICJ2YWx1ZSI6IDEuMDAwMDAwMDU5NjA0NjQ1CiAgICAgIH0sCiAgICAgICJ1bml0IjogIiIsCiAgICAgICJ2YWx1ZV90eXBlIjogIm51bWJlciIsCiAgICAgICJ4IjogMC4wLAogICAgICAieSI6IDAuMAogICAgfSwKICAgIHsKICAgICAgImlkIjogIm91dCIsCiAgICAgICJraW5kIjogIk91dHB1dCIsCiAgICAgICJsYWJlbCI6ICIiLAogICAgICAicGFyYW1zIjoge30sCiAgICAgICJ1bml0IjogIiIsCiAgICAgICJ2YWx1ZV90eXBlIjogIm51bWJlciIsCiAgICAgICJ4IjogMC4wLAogICAgICAieSI6IDAuMAogICAgfQogIF0sCiAgInJldmlzaW9uIjogMCwKICAic2Nhbl9zZWNvbmRzIjogMS4wLAogICJzY2hlbWFfdmVyc2lvbiI6IDEsCiAgInRhcmdldCI6IHsKICAgICJmYW1pbHkiOiAidW5pdmVyc2FsLXJ1bnRpbWUiLAogICAgImZpcm13YXJlIjogIiIsCiAgICAibWF4X25vZGVzIjogMjAwMCwKICAgICJtb2RlbCI6ICIiLAogICAgInBoeXNpY2FsX2lucHV0cyI6IG51bGwsCiAgICAicGh5c2ljYWxfb3V0cHV0cyI6IG51bGwsCiAgICAicmVsZWFzZV9tb2RlIjogIiIKICB9Cn0= *)
