"""Debloat do Windows. Só roda depois do ponto de restauração, e só em listas fechadas.

Defender, Windows Update, rede, áudio e os pacotes da área de trabalho
não entram em lista nenhuma. Um plano não pode pedir um nome fora daqui.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

from orion.fixer.changelog import ChangeLog
from orion.fixer.restore import create_restore_point
from orion.winutil import as_list, read_value, run_powershell_json

NEVER_SERVICES = frozenset(
    {
        "windefend",
        "securityhealthservice",
        "wscsvc",
        "mpssvc",
        "sense",
        "wdnissvc",
        "mdcoresvc",
        "wuauserv",
        "usosvc",
        "bits",
        "dosvc",
        "cryptsvc",
        "eventlog",
        "schedule",
        "dhcp",
        "dnscache",
        "nlasvc",
        "netprofm",
        "bfe",
        "audioendpointbuilder",
        "audiosrv",
        "themes",
        "uxsms",
        "winmgmt",
        "rpcss",
        "dcomlaunch",
        "samss",
        "sppsvc",
        "trustedinstaller",
        "w32time",
        "lanmanworkstation",
        "lanmanserver",
        "eventsystem",
        "fontcache",
        "gpsvc",
        "iphlpsvc",
        "lmhosts",
        "nsi",
        "power",
        "profsvc",
        "sessionenv",
        "shellhwdetection",
        "staterepository",
        "systemeventsbroker",
        "textinputmanagementservice",
        "userprofileservice",
        "appxsvc",
        "clipsvc",
        "installservice",
        "licensemanager",
        "tokenbroker",
        "usermanager",
        "coremessagingregistrar",
        "brokerinfrastructure",
        "lsm",
        "camsvc",
        "cdpsvc",
        "dispbrokerdesktopsvc",
        "storsvc",
        "wpnuserservice",
        "wpnservice",
    }
)

NEVER_PACKAGES = frozenset(
    {
        "Microsoft.Windows.ShellExperienceHost",
        "Microsoft.Windows.StartMenuExperienceHost",
        "Microsoft.Windows.CloudExperienceHost",
        "Microsoft.LockApp",
        "Microsoft.AccountsControl",
        "Microsoft.AAD.BrokerPlugin",
        "Microsoft.CredDialogHost",
        "Microsoft.ECApp",
        "Microsoft.AsyncTextService",
        "Microsoft.BioEnrollment",
        "Microsoft.Win32WebViewHost",
        "Microsoft.SecHealthUI",
        "Microsoft.Windows.SecHealthUI",
        "Microsoft.Windows.SecureAssessmentBrowser",
        "Microsoft.Windows.NarratorQuickStart",
        "Microsoft.Windows.ParentalControls",
        "Microsoft.Windows.OOBENetworkCaptivePortal",
        "Microsoft.Windows.OOBENetworkConnectionFlow",
        "Microsoft.Windows.CapturePicker",
        "Microsoft.Windows.PinningConfirmationDialog",
        "Microsoft.Windows.AssignedAccessLockApp",
        "Microsoft.Windows.Apprep.ChxApp",
        "Microsoft.Windows.XGpuEjectDialog",
        "Microsoft.Windows.PeopleExperienceHost",
        "Microsoft.Windows.ContentDeliveryManager",
        "windows.immersivecontrolpanel",
        "Microsoft.WindowsCalculator",
        "Microsoft.WindowsNotepad",
        "Microsoft.WindowsTerminal",
        "Microsoft.ScreenSketch",
        "Microsoft.Windows.Photos",
        "Microsoft.DesktopAppInstaller",
        "Microsoft.VCLibs.140.00",
        "Microsoft.UI.Xaml.2.0",
        "Microsoft.NET.Native.Framework.2.2",
        "Microsoft.NET.Native.Runtime.2.2",
        "Microsoft.Services.Store.Engagement",
        "Microsoft.WindowsAppRuntime.1",
    }
)

BLOAT_APPS = (
    "Microsoft.BingNews",
    "Microsoft.BingWeather",
    "Microsoft.BingSearch",
    "Microsoft.GetHelp",
    "Microsoft.Getstarted",
    "Microsoft.MicrosoftOfficeHub",
    "Microsoft.MicrosoftSolitaireCollection",
    "Microsoft.People",
    "Microsoft.WindowsFeedbackHub",
    "Microsoft.SkypeApp",
    "Microsoft.Microsoft3DViewer",
    "Microsoft.MSPaint",
    "Microsoft.Print3D",
    "Microsoft.3DBuilder",
    "Microsoft.MixedReality.Portal",
    "Microsoft.OneConnect",
    "Clipchamp.Clipchamp",
    "Microsoft.Copilot",
    "Microsoft.OutlookForWindows",
    "Microsoft.Windows.DevHome",
    "MicrosoftCorporationII.QuickAssist",
    "Microsoft.Todos",
    "Microsoft.PowerAutomateDesktop",
    "Microsoft.549981C3F5F10",
)

MEDIA_APPS = (
    "Microsoft.ZuneMusic",
    "Microsoft.ZuneVideo",
    "Microsoft.WindowsMaps",
    "Microsoft.WindowsAlarms",
    "Microsoft.WindowsSoundRecorder",
    "Microsoft.YourPhone",
    "Microsoft.WindowsCommunicationsApps",
    "Microsoft.Messaging",
    "Microsoft.Office.OneNote",
    "Microsoft.MicrosoftStickyNotes",
    "MicrosoftTeams",
)

XBOX_APPS = (
    "Microsoft.XboxApp",
    "Microsoft.GamingApp",
    "Microsoft.Xbox.TCUI",
    "Microsoft.XboxGameOverlay",
    "Microsoft.XboxGamingOverlay",
    "Microsoft.XboxIdentityProvider",
    "Microsoft.XboxSpeechToTextOverlay",
    "Microsoft.XboxGameCallableUI",
)

STORE_APPS = (
    "Microsoft.WindowsStore",
    "Microsoft.StorePurchaseApp",
)

TELEMETRY_SERVICES = ("DiagTrack", "dmwappushservice")
EXTRA_SERVICES = (
    "Fax",
    "RemoteRegistry",
    "MapsBroker",
    "WalletService",
    "RetailDemo",
    "AJRouter",
    "shpamsvc",
    "wisvc",
    "lfsvc",
    "PhoneSvc",
    "MessagingService",
    "WpcMonSvc",
    "SharedRealitySvc",
    "MixedRealityOpenXRSvc",
)
XBOX_SERVICES = ("XblAuthManager", "XblGameSave", "XboxGipSvc", "XboxNetApiSvc")
ERROR_SERVICES = ("WerSvc", "wercplsupport")

TELEMETRY_TASKS = (
    ("\\Microsoft\\Windows\\Application Experience\\", "Microsoft Compatibility Appraiser"),
    ("\\Microsoft\\Windows\\Application Experience\\", "ProgramDataUpdater"),
    ("\\Microsoft\\Windows\\Application Experience\\", "StartupAppTask"),
    ("\\Microsoft\\Windows\\Application Experience\\", "PcaPatchDbTask"),
    ("\\Microsoft\\Windows\\Customer Experience Improvement Program\\", "Consolidator"),
    ("\\Microsoft\\Windows\\Customer Experience Improvement Program\\", "UsbCeip"),
    ("\\Microsoft\\Windows\\DiskDiagnostic\\", "Microsoft-Windows-DiskDiagnosticDataCollector"),
    ("\\Microsoft\\Windows\\Feedback\\Siuf\\", "DmClient"),
    ("\\Microsoft\\Windows\\Feedback\\Siuf\\", "DmClientOnScenarioDownload"),
    ("\\Microsoft\\Windows\\Diagnosis\\", "Scheduled"),
)
MAP_TASKS = (
    ("\\Microsoft\\Windows\\Maps\\", "MapsToastTask"),
    ("\\Microsoft\\Windows\\Maps\\", "MapsUpdateTask"),
)
ERROR_TASKS = (("\\Microsoft\\Windows\\Windows Error Reporting\\", "QueueReporting"),)

OPTIONAL_FEATURES = (
    "Internet-Explorer-Optional-amd64",
    "MicrosoftWindowsPowerShellV2Root",
    "MicrosoftWindowsPowerShellV2",
    "Printing-XPSServices-Features",
    "WorkFolders-Client",
    "FaxServicesClientPackage",
)
SMB1_FEATURES = ("SMB1Protocol",)

_SERVICE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{1,40}")
_PACKAGE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9.]{2,80}")
_FEATURE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,80}")
_TASK_PATH = re.compile(r"\\(?:[A-Za-z0-9][A-Za-z0-9 ._-]*\\)+")
_TASK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,80}")

CATALOG = [
    {
        "id": "ads_off",
        "group": "Sistema mais leve",
        "title": "Desligar anúncios, dicas e aplicativos sugeridos",
        "detail": "Para a instalação silenciosa de aplicativos, as dicas da tela de bloqueio e o conteúdo patrocinado do menu Iniciar.",
        "impact": "Menos processo de loja e menos aviso por cima do jogo. Não mexe no Defender.",
        "risk": "A Microsoft deixa de sugerir aplicativo. Dá para voltar pelo backup.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "visual_light",
        "group": "Sistema mais leve",
        "title": "Deixar a área de trabalho mais leve",
        "detail": "Desliga transparência, animação da barra, widgets, bate-papo e o feed de notícias. A área de trabalho continua.",
        "impact": "O Windows desenha menos coisa enquanto o jogo está aberto.",
        "risk": "A aparência fica mais simples. Não remove o Explorer.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "startup_delay",
        "group": "Sistema mais leve",
        "title": "Tirar a espera da inicialização",
        "detail": "Zera a pausa que o Windows coloca antes de abrir os programas da inicialização.",
        "impact": "A área de trabalho fica usável um pouco antes.",
        "risk": "Baixo. Os programas da inicialização abrem juntos.",
        "default_on": True,
        "needs_reboot": True,
    },
    {
        "id": "fast_startup",
        "group": "Sistema mais leve",
        "title": "Desligar a inicialização rápida",
        "detail": "O Windows passa a desligar de verdade, em vez de gravar um pedaço da memória.",
        "impact": "Evita driver preso depois de atualizar a placa. A ligação fica um pouco mais lenta.",
        "risk": "Não apaga o arquivo de hibernação. Isso é outro item.",
        "default_on": True,
        "needs_reboot": True,
    },
    {
        "id": "hibernate_off",
        "group": "Sistema mais leve",
        "title": "Apagar o arquivo de hibernação",
        "detail": "Remove o hiberfil.sys. A hibernação e a inicialização rápida deixam de existir.",
        "impact": "Libera vários GB no disco onde o Windows está instalado.",
        "risk": "O computador não hiberna até desfazer. Não apaga arquivo seu.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "search_off",
        "group": "Sistema mais leve",
        "title": "Desligar a indexação da busca",
        "detail": "Para o serviço Windows Search, que fica lendo disco para o menu Iniciar.",
        "impact": "Menos leitura de disco em segundo plano. A busca passa a varrer na hora e fica mais lenta.",
        "risk": "Achar um arquivo pelo menu Iniciar demora mais.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "sysmain_off",
        "group": "Sistema mais leve",
        "title": "Desligar o SysMain",
        "detail": "Para o antigo Superfetch, que tenta adivinhar o programa que você vai abrir.",
        "impact": "Menos atividade no disco. Em HD mecânico um programa do dia a dia pode abrir um pouco mais devagar.",
        "risk": "Não mexe nos jogos que você abre pelo atalho.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "optional_features",
        "group": "Sistema mais leve",
        "title": "Remover recursos opcionais antigos",
        "detail": "Desliga Internet Explorer, PowerShell 2.0, visualizador XPS, Pastas de Trabalho e o cliente de fax, se ainda estiverem ativos.",
        "impact": "Menos componente antigo carregado. O Edge e o PowerShell atual ficam.",
        "risk": "Um programa muito antigo que ainda chama o Internet Explorer pode parar. Pede reinício.",
        "default_on": True,
        "needs_reboot": True,
    },
    {
        "id": "smb1_off",
        "group": "Sistema mais leve",
        "title": "Desligar o SMB 1.0",
        "detail": "Remove o protocolo de rede antigo, se o recurso estiver instalado.",
        "impact": "Menos um serviço de arquivo escutando. Não é o que limita o FPS.",
        "risk": "Um NAS ou HD de rede muito antigo pode sumir. O compartilhamento atual continua.",
        "default_on": False,
        "needs_reboot": True,
    },
    {
        "id": "background_apps",
        "group": "Menos coisa em segundo plano",
        "title": "Impedir aplicativos da Microsoft de rodarem no fundo",
        "detail": "Aplica a política que nega execução em segundo plano para aplicativos empacotados.",
        "impact": "Menos processo acordando com o jogo aberto. Programa clássico, Steam e Epic não entram nisso.",
        "risk": "Aplicativo da Loja deixa de atualizar o próprio bloco enquanto está fechado.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "telemetry_off",
        "group": "Menos coisa em segundo plano",
        "title": "Desligar telemetria e tarefas de avaliação",
        "detail": "Para DiagTrack, o push de diagnóstico e as tarefas de experiência do cliente e de compatibilidade.",
        "impact": "Menos tarefa agendada usando disco e CPU. O Windows Update continua.",
        "risk": "A Microsoft recebe menos diagnóstico deste PC. O Defender não é desligado.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "delivery_local",
        "group": "Menos coisa em segundo plano",
        "title": "Parar de enviar atualização para outros PCs",
        "detail": "A otimização de entrega fica só no modo HTTP. O serviço de atualização não é desligado.",
        "impact": "Este PC deixa de enviar pedaço de atualização para a rede. Baixar atualização continua.",
        "risk": "Baixo. Não desliga o Windows Update.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "error_reporting",
        "group": "Menos coisa em segundo plano",
        "title": "Desligar o relatório de erros",
        "detail": "Para o serviço de relatório e a tarefa que envia a fila de falhas.",
        "impact": "Menos um serviço depois de um programa fechar sozinho.",
        "risk": "Um travamento deixa de ser enviado à Microsoft.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "extra_services",
        "group": "Menos coisa em segundo plano",
        "title": "Desligar fax, registro remoto, mapas e serviços de demonstração",
        "detail": "Para o que existir entre fax, registro remoto, mapas, carteira, loja de demonstração, AllJoyn, localização e telefone.",
        "impact": "Menos serviço parado ocupando partida do Windows.",
        "risk": "Localização de aplicativo e o recurso de fax deixam de funcionar.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "spooler_off",
        "group": "Menos coisa em segundo plano",
        "title": "Desligar a fila de impressão",
        "detail": "Para o serviço Spooler até você desfazer.",
        "impact": "Menos um serviço. Só vale a pena se você não imprime deste PC.",
        "risk": "Impressora e 'imprimir para PDF' param até desfazer.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "remove_bloat",
        "group": "Aplicativos que não são necessários",
        "title": "Remover aplicativos de anúncio, dica e atalho",
        "detail": "Remove notícias, clima, dicas, ajuda, feedback, paciência, hub do Office, pessoas, Skype, 3D, Paint 3D, realidade mista, Clipchamp e Copilot, se estiverem instalados. Não remove Edge, Fotos, Calculadora, Bloco de notas nem a Loja.",
        "impact": "Menos pacote atualizando e aparecendo no menu Iniciar.",
        "risk": "O atalho some. A volta é o ponto de restauração, ou o desfazer se a pasta do pacote ainda existir.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "remove_media",
        "group": "Aplicativos que não são necessários",
        "title": "Remover música, vídeo, mapas, e-mail e telefone da Microsoft",
        "detail": "Remove Groove, Filmes e TV, Mapas, Alarmes, Gravador, Seu Telefone, Email, Mensagens, OneNote, Notas autoadesivas e Teams, se estiverem instalados.",
        "impact": "Menos aplicativo de fábrica em segundo plano.",
        "risk": "Quem usa o Email ou o OneNote deste Windows precisa desmarcar este item.",
        "default_on": True,
        "needs_reboot": False,
    },
    {
        "id": "remove_xbox",
        "group": "Aplicativos que não são necessários",
        "title": "Remover Xbox, Game Bar e serviços da conta Xbox",
        "detail": "Remove os aplicativos do Xbox e desliga os serviços de autenticação e gravação da conta Xbox.",
        "impact": "Menos sobreposição por cima do jogo.",
        "risk": "Minecraft da Microsoft Store e jogo que entra com conta Xbox podem deixar de abrir. Fica desmarcado.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "remove_store",
        "group": "Aplicativos que não são necessários",
        "title": "Remover a Microsoft Store",
        "detail": "Remove a loja e a compra interna. O Windows continua atualizando pelo Windows Update.",
        "impact": "A loja deixa de ocupar o menu e de atualizar aplicativo sozinha.",
        "risk": "Reinstalar um aplicativo da loja fica difícil. Fica desmarcado. A volta segura é o ponto de restauração.",
        "default_on": False,
        "needs_reboot": False,
    },
    {
        "id": "onedrive_off",
        "group": "Aplicativos que não são necessários",
        "title": "Desinstalar o OneDrive",
        "detail": "Roda o desinstalador que já vem no Windows. Não apaga a pasta dos arquivos já baixados.",
        "impact": "O OneDrive sai da inicialização e do Explorer.",
        "risk": "A sincronização para. Arquivo que só estava na nuvem não é baixado por esta ação. Fica desmarcado.",
        "default_on": False,
        "needs_reboot": False,
    },
]

BY_ID = {item["id"]: item for item in CATALOG}

_START_MAP = {"Auto": "Automatic", "Automatic": "Automatic", "Manual": "Manual", "Disabled": "Disabled"}


def catalog_guard() -> list[str]:
    errors = []
    if len(BY_ID) != len(CATALOG):
        errors.append("há id repetido no Debloat")
    packages = [*BLOAT_APPS, *MEDIA_APPS, *XBOX_APPS, *STORE_APPS]
    services = [*TELEMETRY_SERVICES, *EXTRA_SERVICES, *XBOX_SERVICES, *ERROR_SERVICES, "WSearch", "SysMain", "Spooler"]
    for name in packages:
        if not _PACKAGE_NAME.fullmatch(name):
            errors.append(f"nome de pacote inválido: {name}")
        if name in NEVER_PACKAGES:
            errors.append(f"pacote protegido entrou na remoção: {name}")
    for name in services:
        if not _SERVICE_NAME.fullmatch(name):
            errors.append(f"nome de serviço inválido: {name}")
        if name.lower() in NEVER_SERVICES:
            errors.append(f"serviço protegido entrou no Debloat: {name}")
    for path, task_name in (*TELEMETRY_TASKS, *MAP_TASKS, *ERROR_TASKS):
        if not _TASK_PATH.fullmatch(path) or not _TASK_NAME.fullmatch(task_name):
            errors.append(f"tarefa inválida: {path} {task_name}")
    for name in (*OPTIONAL_FEATURES, *SMB1_FEATURES):
        if not _FEATURE_NAME.fullmatch(name):
            errors.append(f"recurso inválido: {name}")
    if set(ACTIONS) != set(BY_ID):
        errors.append("catálogo e ações do Debloat não batem")
    blocked = ("windefend", "wuauserv", "edge", "shellexperiencehost")
    folded = " ".join(packages + services).lower()
    for token in blocked:
        if token in folded:
            errors.append(f"lista do Debloat cita item protegido: {token}")
    return errors


def inspect() -> dict:
    """Lê o que está instalado. Não remove nada."""
    tasks = [*TELEMETRY_TASKS, *MAP_TASKS, *ERROR_TASKS]
    services = [*TELEMETRY_SERVICES, *EXTRA_SERVICES, *XBOX_SERVICES, *ERROR_SERVICES, "WSearch", "SysMain", "Spooler"]
    packages = [*BLOAT_APPS, *MEDIA_APPS, *XBOX_APPS, *STORE_APPS]
    body = f"""
$names = @({_ps_strings(services)})
$foundServices = New-Object System.Collections.Generic.List[object]
foreach ($name in $names) {{
  $svc = Get-CimInstance Win32_Service -Filter \"Name='$name'\" -ErrorAction SilentlyContinue
  if ($svc) {{
    $foundServices.Add(@{{ name = [string]$svc.Name; start = [string]$svc.StartMode; state = [string]$svc.State }})
  }}
}}
$result.services = @($foundServices.ToArray())
$taskRows = @({_ps_tasks(tasks)})
$foundTasks = New-Object System.Collections.Generic.List[object]
foreach ($task in $taskRows) {{
  try {{
    $item = Get-ScheduledTask -TaskPath $task.path -TaskName $task.name -ErrorAction Stop
    $foundTasks.Add(@{{ path = $task.path; name = $task.name; state = [string]$item.State }})
  }} catch {{ }}
}}
$result.tasks = @($foundTasks.ToArray())
$pkgNames = @({_ps_strings(packages)})
$installed = @(Get-AppxPackage | Where-Object {{ $pkgNames -contains $_.Name }} | Select-Object -ExpandProperty Name)
$result.apps = @($installed)
$setup = Join-Path $env:LocalAppData 'Microsoft\\OneDrive\\OneDrive.exe'
$machine = Join-Path $env:ProgramFiles 'Microsoft OneDrive\\OneDrive.exe'
$result.onedrive = [bool]((Test-Path $setup) -or (Test-Path $machine))
"""
    data = _ps(body, timeout=120)
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("message") or "A leitura do Debloat falhou."))
    service_map = {}
    for item in _items(data.get("services")):
        service_map[str(item.get("name"))] = {"start": item.get("start"), "state": item.get("state")}
    task_map = {}
    for item in _items(data.get("tasks")):
        task_map[_task_key(str(item.get("path")), str(item.get("name")))] = str(item.get("state") or "")
    apps = [str(item) for item in as_list(data.get("apps")) if isinstance(item, str)]
    return {
        "apps": apps,
        "services": service_map,
        "tasks": task_map,
        "onedrive": bool(data.get("onedrive")),
    }


def pending(item_id: str, state: dict) -> tuple[bool, str]:
    item = BY_ID[item_id]
    if item_id == "ads_off":
        keys = (
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SilentInstalledAppsEnabled", 0),
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 0),
            ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\CloudContent", "DisableWindowsConsumerFeatures", 1),
        )
        if all(_dword_is(*row) for row in keys):
            return False, "Anúncios e sugestões já estão desligados."
        return True, "Ainda há sugestão ou instalação silenciosa de aplicativo."
    if item_id == "visual_light":
        if _dword_is("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 0):
            return False, "A transparência já está desligada."
        return True, "A área de trabalho ainda usa transparência e animação."
    if item_id == "startup_delay":
        if _dword_is("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize", "StartupDelayInMSec", 0):
            return False, "A espera da inicialização já está zerada."
        return True, "O Windows ainda espera antes de abrir os programas da inicialização."
    if item_id == "fast_startup":
        if _dword_is("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled", 0):
            return False, "A inicialização rápida já está desligada."
        return True, "A inicialização rápida ainda está ligada."
    if item_id == "background_apps":
        if _dword_is("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\AppPrivacy", "LetAppsRunInBackground", 2):
            return False, "Aplicativo empacotado já está impedido de rodar no fundo."
        return True, "Aplicativo da Microsoft ainda pode acordar fechado."
    if item_id == "delivery_local":
        if _dword_is("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization", "DODownloadMode", 0):
            return False, "A atualização já não é enviada para outros PCs."
        return True, "Este PC ainda pode enviar pedaço de atualização para a rede."
    if item_id == "hibernate_off":
        return True, item["detail"]
    if item_id == "onedrive_off":
        if not state.get("onedrive"):
            return False, "O OneDrive não está instalado para este usuário."
        return True, "O OneDrive está neste usuário."
    if item_id == "remove_bloat":
        return _apps_line(state, BLOAT_APPS)
    if item_id == "remove_media":
        return _apps_line(state, MEDIA_APPS)
    if item_id == "remove_xbox":
        apps_needed, apps_line = _apps_line(state, XBOX_APPS)
        services_needed, services_line = _services_line(state, XBOX_SERVICES)
        if not apps_needed and not services_needed:
            return False, "Aplicativos e serviços do Xbox já não estão ativos."
        return True, " ".join(part for part in (apps_line, services_line) if part)
    if item_id == "remove_store":
        return _apps_line(state, STORE_APPS)
    if item_id == "telemetry_off":
        services_needed, services_line = _services_line(state, TELEMETRY_SERVICES)
        tasks_needed, tasks_line = _tasks_line(state, TELEMETRY_TASKS)
        if not services_needed and not tasks_needed:
            return False, "Telemetria e tarefas de avaliação já estão desligadas."
        return True, " ".join(part for part in (services_line, tasks_line) if part)
    if item_id == "error_reporting":
        services_needed, services_line = _services_line(state, ERROR_SERVICES)
        tasks_needed, tasks_line = _tasks_line(state, ERROR_TASKS)
        if not services_needed and not tasks_needed:
            return False, "O relatório de erros já está desligado."
        return True, " ".join(part for part in (services_line, tasks_line) if part)
    if item_id == "extra_services":
        services_needed, services_line = _services_line(state, EXTRA_SERVICES)
        tasks_needed, tasks_line = _tasks_line(state, MAP_TASKS)
        if not services_needed and not tasks_needed:
            return False, "Fax, mapas e os outros serviços dessa lista já estão desligados ou não existem."
        return True, " ".join(part for part in (services_line, tasks_line) if part)
    if item_id == "search_off":
        return _services_line(state, ("WSearch",))
    if item_id == "sysmain_off":
        return _services_line(state, ("SysMain",))
    if item_id == "spooler_off":
        return _services_line(state, ("Spooler",))
    if item_id in {"optional_features", "smb1_off"}:
        return True, item["detail"]
    return item["default_on"], item["detail"]


def build_debloat_plan(ids: list[str]) -> dict:
    return {"kind": "debloat", "fix_ids": [item_id for item_id in ids if item_id in BY_ID]}


def apply_debloat(plan: dict) -> dict:
    steps = []
    ok, message = create_restore_point("ORION antes do debloat")
    steps.append({"id": "restore_point", "ok": ok, "message": message})
    if not ok:
        return {"ok": False, "aborted": True, "reboot": False, "steps": steps, "backup": ""}
    changelog = ChangeLog()
    reboot = False
    failed = False
    for item_id in plan.get("fix_ids") or []:
        handler = ACTIONS.get(str(item_id))
        if handler is None:
            failed = True
            steps.append({"id": item_id, "ok": False, "message": "Item de Debloat desconhecido."})
            continue
        try:
            text, needs_reboot = handler(changelog)
            reboot = reboot or needs_reboot
            steps.append({"id": item_id, "ok": True, "message": text})
        except Exception as error:
            failed = True
            steps.append({"id": item_id, "ok": False, "message": str(error)})
    backup = changelog.save({"steps": steps, "kind": "debloat"})
    return {
        "ok": not failed,
        "aborted": False,
        "reboot": reboot,
        "steps": steps,
        "backup": str(backup),
        "note": (
            "O ponto de restauração cobre registro, serviço e recurso do Windows. "
            "Aplicativo removido volta por esse ponto se o desfazer não achar mais a pasta do pacote."
        ),
    }


def undo_extra(item: dict) -> str:
    kind = str(item.get("kind") or "")
    if kind == "service":
        name = str(item.get("name") or "")
        start = _START_MAP.get(str(item.get("start") or ""), "")
        if not _SERVICE_NAME.fullmatch(name) or name.lower() in NEVER_SERVICES or not start:
            raise RuntimeError("Serviço de backup recusado.")
        running = bool(item.get("running"))
        _ps(
            f"""
Set-Service -Name '{name}' -StartupType {start} -ErrorAction Stop
if (${str(running).lower()}) {{ Start-Service -Name '{name}' -ErrorAction SilentlyContinue }}
$result.message = 'servico'
""",
            timeout=60,
        )
        return f"Serviço restaurado: {name}"
    if kind == "task":
        path = str(item.get("path") or "")
        name = str(item.get("name") or "")
        if not _TASK_PATH.fullmatch(path) or not _TASK_NAME.fullmatch(name):
            raise RuntimeError("Tarefa de backup recusada.")
        _ps(
            f"""
Enable-ScheduledTask -TaskPath '{path}' -TaskName '{name}' -ErrorAction Stop | Out-Null
$result.message = 'tarefa'
""",
            timeout=60,
        )
        return f"Tarefa reativada: {name}"
    if kind == "feature":
        name = str(item.get("name") or "")
        if not _FEATURE_NAME.fullmatch(name):
            raise RuntimeError("Recurso de backup recusado.")
        _ps(
            f"""
Enable-WindowsOptionalFeature -Online -FeatureName '{name}' -NoRestart -ErrorAction Stop | Out-Null
$result.message = 'recurso'
""",
            timeout=180,
        )
        return f"Recurso religado: {name}"
    if kind == "appx":
        return _restore_appx(str(item.get("name") or ""), str(item.get("location") or ""))
    if kind == "onedrive":
        return _restore_onedrive(str(item.get("setup") or ""))
    if kind == "hibernate":
        data = _ps(
            """
powercfg /hibernate on
if ($LASTEXITCODE -ne 0) { throw 'powercfg não religou a hibernação.' }
$result.message = 'hibernacao'
""",
            timeout=60,
        )
        if not data.get("ok", True):
            raise RuntimeError(str(data.get("message") or "Não religou a hibernação."))
        return "Hibernação religada."
    return "Item de backup sem desfazer automático."


def _ads(changelog: ChangeLog) -> tuple[str, bool]:
    rows = [
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SilentInstalledAppsEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SystemPaneSuggestionsEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SoftLandingEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "RotatingLockScreenEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "RotatingLockScreenOverlayEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SubscribedContent-338388Enabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SubscribedContent-338389Enabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SubscribedContent-310093Enabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SubscribedContent-338393Enabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SubscribedContent-353694Enabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SubscribedContent-353696Enabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "ContentDeliveryAllowed", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "OemPreInstalledAppsEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "PreInstalledAppsEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SlideshowEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Privacy", "TailoredExperiencesWithDiagnosticDataEnabled", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ShowSyncProviderNotifications", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "Start_IrisRecommendations", 0),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\UserProfileEngagement", "ScoobeSystemSettingEnabled", 0),
        ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\CloudContent", "DisableWindowsConsumerFeatures", 1),
        ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\CloudContent", "DisableSoftLanding", 1),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Feeds", "ShellFeedsTaskbarViewMode", 2),
        ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\Windows Feeds", "EnableFeeds", 0),
    ]
    _dwords(changelog, rows)
    return "Anúncios, dicas e sugestões desligados.", False


def _visual(changelog: ChangeLog) -> tuple[str, bool]:
    _dwords(
        changelog,
        [
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", 0),
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarAnimations", 0),
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarMn", 0),
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarDa", 0),
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 2),
            ("HKCU", r"Software\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1),
            ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1),
        ],
    )
    changelog.set_value("HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", "sz", "0")
    changelog.set_value("HKCU", r"Control Panel\Desktop", "MenuShowDelay", "sz", "0")
    return "Transparência, animação e feed desligados.", False


def _startup_delay(changelog: ChangeLog) -> tuple[str, bool]:
    _dwords(changelog, [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize", "StartupDelayInMSec", 0)])
    return "A espera da inicialização foi zerada.", True


def _fast_startup(changelog: ChangeLog) -> tuple[str, bool]:
    _dwords(changelog, [("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled", 0)])
    return "Inicialização rápida desligada. Vale no próximo desligamento.", True


def _background(changelog: ChangeLog) -> tuple[str, bool]:
    _dwords(
        changelog,
        [
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications", "GlobalUserDisabled", 1),
            ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Search", "BackgroundAppGlobalToggle", 0),
            ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\AppPrivacy", "LetAppsRunInBackground", 2),
        ],
    )
    return "Aplicativos empacotados ficam impedidos de rodar fechados.", False


def _delivery(changelog: ChangeLog) -> tuple[str, bool]:
    _dwords(changelog, [("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DeliveryOptimization", "DODownloadMode", 0)])
    return "Atualização deixa de ser enviada para outros PCs. O Windows Update continua.", False


def _telemetry(changelog: ChangeLog) -> tuple[str, bool]:
    _dwords(
        changelog,
        [
            ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 0),
            ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\DataCollection", "AllowTelemetry", 0),
        ],
    )
    service_text = _disable_services(changelog, TELEMETRY_SERVICES)
    task_text = _disable_tasks(changelog, TELEMETRY_TASKS)
    return f"{service_text} {task_text} O Windows Update não foi desligado.", False


def _errors(changelog: ChangeLog) -> tuple[str, bool]:
    _dwords(
        changelog,
        [
            ("HKLM", r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled", 1),
            ("HKCU", r"Software\Microsoft\Windows\Windows Error Reporting", "Disabled", 1),
        ],
    )
    service_text = _disable_services(changelog, ERROR_SERVICES)
    task_text = _disable_tasks(changelog, ERROR_TASKS)
    return f"{service_text} {task_text}", False


def _extra(changelog: ChangeLog) -> tuple[str, bool]:
    service_text = _disable_services(changelog, EXTRA_SERVICES)
    task_text = _disable_tasks(changelog, MAP_TASKS)
    return f"{service_text} {task_text}", False


def _search(changelog: ChangeLog) -> tuple[str, bool]:
    return _disable_services(changelog, ("WSearch",)), False


def _sysmain(changelog: ChangeLog) -> tuple[str, bool]:
    return _disable_services(changelog, ("SysMain",)), False


def _spooler(changelog: ChangeLog) -> tuple[str, bool]:
    return _disable_services(changelog, ("Spooler",)), False


def _hibernate(changelog: ChangeLog) -> tuple[str, bool]:
    data = _ps(
        """
powercfg /hibernate off
if ($LASTEXITCODE -ne 0) { throw 'O Windows não apagou o arquivo de hibernação.' }
$result.message = 'hibernacao'
""",
        timeout=60,
    )
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("message") or "Não apagou a hibernação."))
    changelog.remember("hibernate")
    return "Arquivo de hibernação removido. Os seus arquivos não foram apagados.", False


def _onedrive(changelog: ChangeLog) -> tuple[str, bool]:
    data = _ps(
        """
Get-Process -Name OneDrive -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
$setup = Join-Path $env:SystemRoot 'System32\\OneDriveSetup.exe'
if (-not (Test-Path $setup)) { $setup = Join-Path $env:SystemRoot 'SysWOW64\\OneDriveSetup.exe' }
if (-not (Test-Path $setup)) { throw 'O instalador do OneDrive não está no Windows.' }
Start-Process -FilePath $setup -ArgumentList '/uninstall' -Wait
$result.items = @(@{ setup = $setup })
$result.message = 'onedrive'
""",
        timeout=120,
    )
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("message") or "Não desinstalou o OneDrive."))
    setup = ""
    for item in _items(data):
        setup = str(item.get("setup") or "")
    if setup:
        changelog.remember("onedrive", setup=setup)
    return "OneDrive desinstalado. A pasta dos arquivos já baixados continua no lugar.", False


def _remove_bloat(changelog: ChangeLog) -> tuple[str, bool]:
    return _remove_packages(changelog, BLOAT_APPS)


def _remove_media(changelog: ChangeLog) -> tuple[str, bool]:
    return _remove_packages(changelog, MEDIA_APPS)


def _remove_xbox(changelog: ChangeLog) -> tuple[str, bool]:
    text, _reboot = _remove_packages(changelog, XBOX_APPS)
    services = _disable_services(changelog, XBOX_SERVICES)
    return f"{text} {services}", False


def _remove_store(changelog: ChangeLog) -> tuple[str, bool]:
    return _remove_packages(changelog, STORE_APPS)


def _optional(changelog: ChangeLog) -> tuple[str, bool]:
    return _disable_features(changelog, OPTIONAL_FEATURES)


def _smb1(changelog: ChangeLog) -> tuple[str, bool]:
    return _disable_features(changelog, SMB1_FEATURES)


ACTIONS = {
    "ads_off": _ads,
    "visual_light": _visual,
    "startup_delay": _startup_delay,
    "fast_startup": _fast_startup,
    "hibernate_off": _hibernate,
    "search_off": _search,
    "sysmain_off": _sysmain,
    "optional_features": _optional,
    "smb1_off": _smb1,
    "background_apps": _background,
    "telemetry_off": _telemetry,
    "delivery_local": _delivery,
    "error_reporting": _errors,
    "extra_services": _extra,
    "spooler_off": _spooler,
    "remove_bloat": _remove_bloat,
    "remove_media": _remove_media,
    "remove_xbox": _remove_xbox,
    "remove_store": _remove_store,
    "onedrive_off": _onedrive,
}


def _dwords(changelog: ChangeLog, rows: list[tuple[str, str, str, int]]) -> None:
    for root, path, name, value in rows:
        changelog.set_value(root, path, name, "dword", int(value))


def _dword_is(root: str, path: str, name: str, expected: int) -> bool:
    exists, _reg_type, value = read_value(root, path, name)
    return exists and value == expected


def _apps_line(state: dict, names: tuple[str, ...]) -> tuple[bool, str]:
    found = [name for name in names if name in set(state.get("apps") or [])]
    if not found:
        return False, "Nenhum desses aplicativos está instalado para este usuário."
    preview = ", ".join(found[:10])
    more = f" e mais {len(found) - 10}" if len(found) > 10 else ""
    return True, f"Instalados agora: {preview}{more}."


def _services_line(state: dict, names: tuple[str, ...]) -> tuple[bool, str]:
    pending_names = []
    known = state.get("services") or {}
    for name in names:
        info = known.get(name)
        if not info:
            continue
        if str(info.get("start") or "").lower() == "disabled":
            continue
        pending_names.append(name)
    if not pending_names:
        return False, "Esses serviços já estão desligados ou não existem neste Windows."
    return True, "Serviços ainda ativos: " + ", ".join(pending_names) + "."


def _tasks_line(state: dict, tasks: tuple[tuple[str, str], ...]) -> tuple[bool, str]:
    known = state.get("tasks") or {}
    pending_names = []
    for path, name in tasks:
        state_name = known.get(_task_key(path, name))
        if state_name and state_name.lower() != "disabled":
            pending_names.append(name)
    if not pending_names:
        return False, ""
    return True, "Tarefas ainda ativas: " + ", ".join(pending_names) + "."


def _task_key(path: str, name: str) -> str:
    return f"{path}|{name}"


def _guard_services(names: tuple[str, ...] | list[str]) -> None:
    for name in names:
        if not _SERVICE_NAME.fullmatch(name) or name.lower() in NEVER_SERVICES:
            raise RuntimeError(f"Serviço protegido ou inválido: {name}")


def _guard_packages(names: tuple[str, ...] | list[str]) -> None:
    for name in names:
        if not _PACKAGE_NAME.fullmatch(name) or name in NEVER_PACKAGES:
            raise RuntimeError(f"Pacote protegido ou inválido: {name}")


def _disable_services(changelog: ChangeLog, names: tuple[str, ...] | list[str]) -> str:
    _guard_services(names)
    quoted = _ps_strings(names)
    data = _ps(
        f"""
$names = @({quoted})
$changed = New-Object System.Collections.Generic.List[object]
foreach ($name in $names) {{
  $svc = Get-CimInstance Win32_Service -Filter \"Name='$name'\" -ErrorAction SilentlyContinue
  if (-not $svc) {{ continue }}
  $start = [string]$svc.StartMode
  $state = [string]$svc.State
  if ($start -eq 'Disabled') {{ continue }}
  Set-Service -Name $name -StartupType Disabled -ErrorAction Stop
  if ($state -eq 'Running') {{ Stop-Service -Name $name -Force -ErrorAction SilentlyContinue }}
  $changed.Add(@{{ name = $name; start = $start; state = $state }})
  $result.items = @($changed.ToArray())
}}
$result.items = @($changed.ToArray())
$result.message = 'servicos'
""",
        timeout=90,
    )
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("message") or "Não desligou os serviços."))
    changed = []
    for item in _items(data):
        name = str(item.get("name") or "")
        start = str(item.get("start") or "")
        if not name:
            continue
        changelog.remember("service", name=name, start=start, running=str(item.get("state") or "").lower() == "running")
        changed.append(name)
    if not changed:
        return "Nenhum serviço dessa lista precisava ser desligado."
    return "Serviços desligados: " + ", ".join(changed) + "."


def _disable_tasks(changelog: ChangeLog, tasks: tuple[tuple[str, str], ...]) -> str:
    for path, name in tasks:
        if not _TASK_PATH.fullmatch(path) or not _TASK_NAME.fullmatch(name):
            raise RuntimeError(f"Tarefa recusada: {name}")
    data = _ps(
        f"""
$rows = @({_ps_tasks(tasks)})
$changed = New-Object System.Collections.Generic.List[object]
foreach ($task in $rows) {{
  try {{
    $item = Get-ScheduledTask -TaskPath $task.path -TaskName $task.name -ErrorAction Stop
  }} catch {{ continue }}
  if ([string]$item.State -eq 'Disabled') {{ continue }}
  Disable-ScheduledTask -TaskPath $task.path -TaskName $task.name -ErrorAction Stop | Out-Null
  $changed.Add(@{{ path = $task.path; name = $task.name }})
  $result.items = @($changed.ToArray())
}}
$result.items = @($changed.ToArray())
$result.message = 'tarefas'
""",
        timeout=90,
    )
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("message") or "Não desligou as tarefas."))
    changed = []
    for item in _items(data):
        path = str(item.get("path") or "")
        name = str(item.get("name") or "")
        if not name:
            continue
        changelog.remember("task", path=path, name=name)
        changed.append(name)
    if not changed:
        return "Nenhuma tarefa dessa lista precisava ser desligada."
    return "Tarefas desligadas: " + ", ".join(changed) + "."


def _disable_features(changelog: ChangeLog, names: tuple[str, ...]) -> tuple[str, bool]:
    for name in names:
        if not _FEATURE_NAME.fullmatch(name):
            raise RuntimeError(f"Recurso recusado: {name}")
    data = _ps(
        f"""
$names = @({_ps_strings(names)})
$changed = New-Object System.Collections.Generic.List[object]
foreach ($name in $names) {{
  $feat = Get-WindowsOptionalFeature -Online -FeatureName $name -ErrorAction SilentlyContinue
  if (-not $feat) {{ continue }}
  if ([string]$feat.State -ne 'Enabled') {{ continue }}
  $done = Disable-WindowsOptionalFeature -Online -FeatureName $name -NoRestart -ErrorAction Stop
  if ($done.RestartNeeded) {{ $result.reboot = $true }}
  $changed.Add(@{{ name = $name }})
  $result.items = @($changed.ToArray())
}}
$result.items = @($changed.ToArray())
$result.message = 'recursos'
""",
        timeout=240,
    )
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("message") or "Não desligou os recursos."))
    changed = []
    for item in _items(data):
        name = str(item.get("name") or "")
        if not name:
            continue
        changelog.remember("feature", name=name)
        changed.append(name)
    if not changed:
        return "Nenhum recurso dessa lista estava ativo.", False
    return "Recursos desligados: " + ", ".join(changed) + ".", True


def _remove_packages(changelog: ChangeLog, names: tuple[str, ...]) -> tuple[str, bool]:
    _guard_packages(names)
    data = _ps(
        f"""
$names = @({_ps_strings(names)})
$changed = New-Object System.Collections.Generic.List[object]
$packages = @(Get-AppxPackage | Where-Object {{ $names -contains $_.Name }})
foreach ($pkg in $packages) {{
  try {{
    try {{
      Remove-AppxPackage -Package $pkg.PackageFullName -AllUsers -ErrorAction Stop
    }} catch {{
      Remove-AppxPackage -Package $pkg.PackageFullName -ErrorAction Stop
    }}
    $changed.Add(@{{ name = [string]$pkg.Name; full = [string]$pkg.PackageFullName; location = [string]$pkg.InstallLocation; error = '' }})
  }} catch {{
    $changed.Add(@{{ name = [string]$pkg.Name; full = ''; location = ''; error = [string]$_.Exception.Message }})
  }}
  $result.items = @($changed.ToArray())
}}
try {{
  $prov = @(Get-AppxProvisionedPackage -Online | Where-Object {{ $names -contains $_.DisplayName }})
  foreach ($pkg in $prov) {{
    Remove-AppxProvisionedPackage -Online -PackageName $pkg.PackageName -ErrorAction SilentlyContinue | Out-Null
  }}
}} catch {{ }}
$result.items = @($changed.ToArray())
$result.message = 'pacotes'
""",
        timeout=240,
    )
    removed = []
    failed = []
    for item in _items(data):
        name = str(item.get("name") or "")
        if item.get("error"):
            failed.append(f"{name}: {item.get('error')}")
            continue
        if item.get("full"):
            changelog.remember("appx", name=name, location=str(item.get("location") or ""))
            removed.append(name)
    if not data.get("ok", True) and not removed:
        raise RuntimeError(str(data.get("message") or "Não removeu os aplicativos."))
    if not removed and failed:
        raise RuntimeError("; ".join(failed)[:500])
    if not removed:
        return "Nenhum desses aplicativos estava instalado.", False
    text = "Removidos: " + ", ".join(removed) + "."
    if failed:
        text += " Não saíram: " + "; ".join(failed)[:300]
    return text, False


def _restore_appx(name: str, location: str) -> str:
    if not _PACKAGE_NAME.fullmatch(name):
        raise RuntimeError("Pacote de backup recusado.")
    if not location:
        return f"{name}: sem pasta para registrar de novo. Use o ponto de restauração."
    folder = Path(location).resolve()
    windowsapps = Path(r"C:\Program Files\WindowsApps").resolve()
    if windowsapps != folder and windowsapps not in folder.parents:
        raise RuntimeError("A pasta do pacote está fora do WindowsApps.")
    manifest = folder / "AppxManifest.xml"
    if not manifest.is_file():
        return f"{name}: a pasta do pacote já não está no Windows. Use o ponto de restauração."
    safe = str(manifest).replace("'", "''")
    data = _ps(
        f"""
Add-AppxPackage -DisableDevelopmentMode -Register '{safe}' -ErrorAction Stop
$result.message = 'appx'
""",
        timeout=120,
    )
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("message") or f"Não registrou {name}."))
    return f"Aplicativo registrado de novo: {name}"


def _restore_onedrive(setup: str) -> str:
    folder = Path(setup).resolve() if setup else None
    system = Path(__import__("os").environ.get("SystemRoot", r"C:\Windows")).resolve()
    if folder is None or not folder.is_file() or system not in folder.parents or folder.name.lower() != "onedrivesetup.exe":
        return "O instalador do OneDrive não foi encontrado. Use o ponto de restauração."
    safe = str(folder).replace("'", "''")
    data = _ps(
        f"""
Start-Process -FilePath '{safe}' -Wait
$result.message = 'onedrive'
""",
        timeout=120,
    )
    if not data.get("ok", True):
        raise RuntimeError(str(data.get("message") or "Não reinstalou o OneDrive."))
    return "OneDrive instalado de novo."


def _ps_strings(names: tuple[str, ...] | list[str]) -> str:
    return ",".join("'" + name + "'" for name in names)


def _ps_tasks(tasks: tuple[tuple[str, str], ...] | list[tuple[str, str]]) -> str:
    return ",".join(f"@{{ path = '{path}'; name = '{name}' }}" for path, name in tasks)


def _items(value) -> list[dict]:
    rows = []
    for item in as_list(value):
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _ps(body: str, timeout: int) -> dict:
    out = Path(tempfile.gettempdir()) / f"orion-debloat-{uuid.uuid4().hex}.json"
    script = (
        "$result = @{ ok = $true; message = ''; items = @(); reboot = $false; "
        "services = @(); tasks = @(); apps = @(); onedrive = $false }\n"
        "try {\n"
        f"{body}\n"
        "} catch {\n"
        "  $result.ok = $false\n"
        "  $result.message = [string]$_.Exception.Message\n"
        "}\n"
        f"$result | ConvertTo-Json -Depth 6 -Compress | Out-File -FilePath '{out}' -Encoding utf8\n"
    )
    return run_powershell_json(script, out, timeout=timeout)
