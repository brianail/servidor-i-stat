' Inicializador 100% invisível em segundo plano do Servidor LYDA i-STAT
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir
WshShell.Run "cmd /c watchdog_server.bat", 0, False
