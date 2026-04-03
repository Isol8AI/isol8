use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::TrayIconBuilder,
    AppHandle,
};

pub fn create_tray(app: &AppHandle) -> tauri::Result<()> {
    let title = MenuItemBuilder::with_id("title", "Isol8 Desktop")
        .enabled(false)
        .build(app)?;
    let status = MenuItemBuilder::with_id("status", "Ready")
        .enabled(false)
        .build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;

    let menu = MenuBuilder::new(app)
        .item(&title)
        .separator()
        .item(&status)
        .separator()
        .item(&quit)
        .build()?;

    let _tray = TrayIconBuilder::with_id("main")
        .tooltip("Isol8")
        .menu(&menu)
        .on_menu_event(|app, event| {
            if event.id().as_ref() == "quit" {
                app.exit(0);
            }
        })
        .build(app)?;

    Ok(())
}
