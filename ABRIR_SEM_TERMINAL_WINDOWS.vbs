' Inicializador invisível para Windows (Abre o sistema LYDA i-STAT sem nenhuma janela preta de CMD/Terminal)
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
strDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir

If FSO.FileExists(strDir & "\dist\LYDA_iSTAT_Estoque.exe") Then
    WshShell.Run Chr(34) & strDir & "\dist\LYDA_iSTAT_Estoque.exe" & Chr(34), 0, False
ElseIf FSO.FileExists(strDir & "\.venv\Scripts\pythonw.exe") Then
    WshShell.Run Chr(34) & strDir & "\.venv\Scripts\pythonw.exe" & Chr(34) & " " & Chr(34) & strDir & "\main.py" & Chr(34), 0, False
Else
    WshShell.Run "cmd /c INICIAR_SISTEMA_LYDA.bat", 0, False
End If

