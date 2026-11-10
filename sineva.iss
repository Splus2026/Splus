; Установщик Синевы+ (Inno Setup 6). Собирается скриптом build_installer.bat:
;   ISCC /DVariant=full    sineva.iss   ->  installer\Sineva_Setup_full_<версия>.exe
;   ISCC /DVariant=compact sineva.iss   ->  installer\Sineva_Setup_compact_<версия>.exe
; Перед этим нужно собрать программу (build_exe.bat): берутся папки dist\Sineva_full и dist\Sineva_compact.

#ifndef Variant
  #define Variant "full"
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#if Variant == "full"
  #define VariantTitle "полная, с MiniLM"
#else
  #define VariantTitle "компактная"
#endif
; Один AppId у обоих вариантов: они ставятся в одну папку (по умолчанию D:\Splus) и заменяют друг друга.
#define VariantGuid "{{7B1C5E52-3D0A-4F6B-9A41-5C2E8D6F1A01}"

[Setup]
AppId={#VariantGuid}
AppName=Синева+ ({#VariantTitle})
AppVersion={#AppVersion}
AppPublisher=Синева+
DefaultDirName={code:GetDefaultDir}
DefaultGroupName=Синева+ ({#VariantTitle})
DisableProgramGroupPage=yes
; Программа пишет рядом с собой (mconfig.ini, marks.db, DB, индексы, модели, Manticore),
; поэтому ставим для текущего пользователя — в Program Files без прав администратора писать нельзя.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=installer
OutputBaseFilename=Sineva_Setup_{#Variant}_{#AppVersion}
Compression=lzma2/ultra64
LZMAUseSeparateProcess=yes
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Sineva.exe
UninstallDisplayName=Синева+ ({#VariantTitle})
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
; Вся программа, кроме файлов, которые пользователь правит сам: при обновлении их нельзя затирать.
Source: "dist\Sineva_{#Variant}\*"; DestDir: "{app}"; \
  Excludes: "mconfig.ini,key_concepts.txt,readme.txt,DB\*,Manticore\bin\manticore.conf,Manticore\bin\searchd.pid,Manticore\log\*"; \
  Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\Sineva_{#Variant}\DB\*"; DestDir: "{app}\DB"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs skipifsourcedoesntexist
Source: "dist\Sineva_{#Variant}\mconfig.ini"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist
Source: "dist\Sineva_{#Variant}\key_concepts.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist
Source: "dist\Sineva_{#Variant}\readme.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\Синева+"; Filename: "{app}\Sineva.exe"; WorkingDir: "{app}"
Name: "{group}\Удалить Синеву+"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Синева+"; Filename: "{app}\Sineva.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[InstallDelete]
; Компактный поверх полного: убираем оставшиеся библиотеки MiniLM.
Type: filesandordirs; Name: "{app}\_internal\Manticore"
Type: filesandordirs; Name: "{app}\_internal\DB"
Type: filesandordirs; Name: "{app}\_internal\torch"
Type: filesandordirs; Name: "{app}\_internal\sentence_transformers"
Type: filesandordirs; Name: "{app}\_internal\transformers"

[Run]
Filename: "{app}\Sineva.exe"; Description: "Запустить Синеву+"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
// Папка по умолчанию — D:\Splus; если диска D: нет, берём папку программ текущего пользователя.
function GetDefaultDir(Param: String): String;
begin
  if DirExists('D:\') then
    Result := 'D:\Splus'
  else
    Result := ExpandConstant('{autopf}\Splus');
end;

// При удалении данные пользователя (база DB, индексы, модели, настройки, подчёркивания) по умолчанию
// ОСТАЮТСЯ: удаляется только то, что поставил установщик. Стереть их можно, ответив «Да» на вопрос.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dirs: array of String;
  I: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  if UninstallSilent then
    Exit;
  if MsgBox('Удалить также ваши данные: папки DB, индексы, векторные модели, настройки, '#13#10 +
            'подчёркивания и словарь ключевых понятий?'#13#10#13#10 +
            'Если вы собираетесь поставить программу снова, нажмите «Нет».',
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    Exit;
  SetArrayLength(Dirs, 8);
  Dirs[0] := ExpandConstant('{app}\DB');
  Dirs[1] := ExpandConstant('{app}\indicies_fts5');
  Dirs[2] := ExpandConstant('{app}\indicies_mc');
  Dirs[3] := ExpandConstant('{app}\Manticore');
  Dirs[4] := ExpandConstant('{app}\vector_models');
  Dirs[5] := ExpandConstant('{app}\.tmp');
  Dirs[6] := ExpandConstant('{app}\_internal');
  Dirs[7] := ExpandConstant('{app}');
  for I := 0 to GetArrayLength(Dirs) - 1 do
    DelTree(Dirs[I], True, True, True);
end;
