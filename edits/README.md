# edits/

社群送來的修改申請，一份一個檔案（`issue-{編號}.json`），由 issue 自動產生（`scripts/issue-to-edit.mjs`）。

這裡**不是資料**：Airtable 才是正本，`data/` 是每天從 Airtable 重寫的鏡像。
申請合併進 main 之後，`.github/workflows/apply-edits.yml` 會用 `scripts/apply-edit.mjs` 寫回 Airtable，
隔天的同步再把結果帶回 `data/`。

寫回之前會比對 Airtable 現在的值是否還是申請時的值（`from`）；不是的話整份不寫，在 PR 上留言。
