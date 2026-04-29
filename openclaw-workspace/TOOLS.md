# TOOLS.md - 本地工具備註

Skills 定義工具「怎麼用」。這個檔案則記錄「這個 workspace 特有的設定」。

## 可以寫什麼

例如：

- 攝影機名稱與位置
- SSH 主機與 alias
- TTS 偏好的聲音
- 喇叭或房間名稱
- 裝置暱稱
- 任何和這個環境有關的細節

## 範例

```markdown
### 攝影機

- living-room → 主要區域，180 度廣角
- front-door → 入口，移動偵測觸發

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- 偏好聲音："Nova"（溫暖，帶一點英式感）
- 預設喇叭：Kitchen HomePod
```

## 為什麼要分開

Skills 是可共用的；你的本地設定是私人的。把兩者分開，可以在更新 skills 時不覆蓋本地備註，也能避免分享 skills 時洩漏自己的基礎設施資訊。

---

把能幫你工作的細節寫在這裡。這是你的本地小抄。
