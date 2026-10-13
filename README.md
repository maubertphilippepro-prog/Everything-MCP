# Passerelle Claude ↔ Everything

Vous posez une question en langage naturel dans Claude Desktop (« les PDF du chantier Martin modifiés cette semaine »), Claude la traduit en syntaxe Everything (`ext:pdf *martin* dm:thisweek`), le serveur local l'exécute et Claude vous présente les résultats.

Tout reste sur votre poste : le serveur ne lit que l'index d'Everything (noms, chemins, tailles, dates), il ne modifie rien.

## 1. Prérequis

1. **Everything** lancé (icône dans la zone de notification).
2. **es.exe**, l'interface en ligne de commande d'Everything : sur voidtools.com → *Downloads* → *Command-line Interface*. Dézippez `es.exe` dans le dossier d'Everything (`C:\Program Files\Everything\`).
   Test dans un terminal : `"C:\Program Files\Everything\es.exe" -n 5 *.pdf` doit lister 5 PDF.
3. **Python 3.10+** puis, dans un terminal :
   ```
   pip install mcp
   ```

## 2. Installation

1. Copiez `server.py` dans un dossier fixe, par ex. `C:\Outils\everything_mcp\`.
2. Ouvrez le fichier de configuration de Claude Desktop : *Paramètres → Développeur → Modifier la configuration* (fichier `%APPDATA%\Claude\claude_desktop_config.json`).
3. Ajoutez le bloc suivant (fusionnez avec `mcpServers` s'il existe déjà) :

```json
{
  "mcpServers": {
    "everything": {
      "command": "python",
      "args": ["C:\\Outils\\everything_mcp\\server.py"],
      "env": {
        "ES_PATH": "C:\\Program Files\\Everything\\es.exe"
      }
    }
  }
}
```

4. Quittez complètement Claude Desktop (clic droit sur l'icône → Quitter) et relancez-le. L'outil `everything_search` apparaît dans la liste des outils.

## 3. Exemples de demandes

- « Trouve les DWG modifiés depuis lundi sur D: »
- « Quels sont mes 20 plus gros fichiers vidéo ? »
- « Y a-t-il des doublons de *CCTP* dans Documents ? »
- « Les photos en portrait de plus de 4000 px prises en 2025 »
- « Les Excel qui contiennent "DPGF" dans le dossier Chantiers » (recherche dans le contenu : lente, toujours restreinte à un dossier)

### Voir les résultats dans Everything

Deux outils sont disponibles :

- `everything_search` : Claude récupère les résultats et vous répond dans la conversation.
- `everything_show` : Claude affiche la requête dans la fenêtre d'Everything, où vous pouvez trier, prévisualiser et ouvrir les fichiers vous-même. Un fichier précis peut être pré-sélectionné.

Il suffit de le demander : « montre-les dans Everything », « ouvre cette recherche dans Everything », ou « cherche… et affiche aussi dans Everything ».

## 4. Options (variables `env`)

| Variable | Rôle | Défaut |
|---|---|---|
| `ES_PATH` | Chemin de es.exe | `C:\Program Files\Everything\es.exe` |
| `EVERYTHING_EXE` | Chemin d'Everything.exe (pour `everything_show`) | même dossier que es.exe |
| `EVERYTHING_INSTANCE` | Nom d'instance, ex. `1.5a` pour Everything 1.5 alpha | vide |
| `EVERYTHING_MAX_RESULTS` | Plafond de résultats par appel | `500` |
| `EVERYTHING_BACKEND` | `es` ou `http` | `es` |
| `EVERYTHING_HTTP_URL` | Adresse du serveur HTTP d'Everything | `http://127.0.0.1:8080` |

**Variante sans es.exe** : activez le serveur HTTP d'Everything (*Outils → Options → Serveur HTTP*, liez-le à `127.0.0.1` uniquement), puis mettez `"EVERYTHING_BACKEND": "http"` dans `env`.

## 5. Dépannage

- **« es.exe a échoué (code 8) »** : Everything n'est pas lancé, ou vous utilisez la 1.5 alpha → ajoutez `"EVERYTHING_INSTANCE": "1.5a"`.
- **« es.exe introuvable »** : vérifiez `ES_PATH` (doubles antislashs dans le JSON).
- **Option inconnue signalée par es.exe** (`-size-format`, `-date-format`…) : mettez es.exe à jour.
- **Accents mal affichés** : signalez-le, l'encodage de sortie de es.exe dépend de la version.
- **La fenêtre d'Everything se met à jour mais reste en arrière-plan** : Windows empêche parfois une application lancée en tâche de fond de prendre le focus ; l'icône clignote dans la barre des tâches, cliquez dessus.
- **L'outil n'apparaît pas** : `python` doit être dans le PATH ; sinon indiquez le chemin complet (`C:\\Python312\\python.exe`) dans `command`.
