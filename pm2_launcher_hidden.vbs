' Hidden launcher for PM2 on Windows.
' VBScript's Run method with windowStyle=0 hides the console window completely.
Set objShell = CreateObject("WScript.Shell")

Dim nodeExe, scriptPath, args
nodeExe = objShell.ExpandEnvironmentStrings("%APPDATA%") & "\nvm\v22.14.0\node.exe"
scriptPath = Replace(WScript.ScriptFullName, WScript.ScriptName, "") & "pm2_launcher.js"
args = "api_server.py"

' windowStyle 0 = hidden
objShell.Run """" & nodeExe & """ """ & scriptPath & """ " & args, 0, True
