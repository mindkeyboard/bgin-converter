import * as vscode from "vscode";
import { Backend } from "./backend";

/** Explicit resource conversion never runs as a side effect of editing BGIN. */
export async function convertTexture(backend: Backend) {
  const ru = vscode.workspace.getConfiguration("bgin").get<string>("language", "en") === "ru";
  const files = await vscode.window.showOpenDialog({ canSelectMany: false, title: ru ? "Исходная PVR-текстура (расширение может быть .tga)" : "Source PVR texture (may use .tga extension)" });
  if (!files?.[0]) return;
  const method = await vscode.window.showQuickPick([
    { label: ru ? "Снять дополнительное сжатие" : "Remove outer compression", description: ru ? "GPU-блоки и уровни mip сохраняются; ETC2/ASTC для старого режима будут отклонены" : "Preserve GPU blocks and mips; reject ETC2/ASTC for older targets", id: "unwrap" },
    { label: "RGBA8", description: ru ? "Перекодировать все уровни mip; размер увеличится" : "Decode all mip levels; increases file size", id: "rgba8" },
  ], { title: ru ? "Отдельная конвертация текстуры для ~1.6.0" : "Separate texture conversion for ~1.6.0" });
  if (!method) return;
  const output = await vscode.window.showSaveDialog({ defaultUri: files[0].with({ path: files[0].path + ".converted.tga" }), title: ru ? "Сохранить отдельную текстуру" : "Save separate texture" });
  if (!output) return;
  try {
    const result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: ru ? "Конвертация текстуры…" : "Converting texture…" }, () => backend.call("convert_texture", { source: files[0].fsPath, destination: output.fsPath, method: method.id, target_format: "a8-1.6.0" }));
    await vscode.window.showInformationMessage(ru
      ? `Текстура сохранена: ${result.bytes} байт. Загрузка игрой не проверена. Отдельную альфа-текстуру конвертируйте отдельной командой.`
      : `Texture saved: ${result.bytes} bytes. Game loading is unverified. Convert any separate alpha texture explicitly as well.`);
  } catch (error) { await vscode.window.showErrorMessage(String(error)); }
}
