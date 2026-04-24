# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 블로그 관리 허브 EXE 빌드
빌드: pyinstaller build.spec
결과: dist/블로그관리허브/ 폴더 (안에 .exe + 런타임 파일들)
"""

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # selenium 관련
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.common.action_chains',
        'selenium.webdriver.common.by',
        'selenium.webdriver.common.keys',
        'selenium.webdriver.support.expected_conditions',
        'selenium.webdriver.support.ui',
        # webdriver_manager
        'webdriver_manager.chrome',
        'webdriver_manager.core.download_manager',
        'webdriver_manager.core.driver',
        # google auth / gspread
        'google.auth',
        'google.auth.transport',
        'google.auth.transport.requests',
        'google.oauth2.service_account',
        'gspread',
        'gspread.auth',
        # 기타
        'pyperclip',
        'requests',
        # 이 프로젝트의 패키지/모듈
        'shared',
        'shared.paths',
        'shared.sheets_client',
        'shared.browser_manager',
        'shared.gui_helpers',
        'tabs',
        'tabs.tab_reply_bot',
        'tabs.tab_comment_monitor',
        'tabs.tab_link_checker',
        'tabs.tab_auto_publisher',
        'tabs.tab_comment_checker',
        'vendor',
        'vendor.blog_post',
        'vendor.sheets_handler',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='블로그관리허브',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI 앱 — 콘솔 창 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='블로그관리허브',
)
