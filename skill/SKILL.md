---
name: everything
description: Recherche, exploration et COPIE de fichiers et dossiers sur ce PC Windows via Everything (voidtools), y compris recherche dans le contenu de tout format. Utiliser quand l'utilisateur tape /everything suivi de sa demande en langage naturel, ou demande de trouver, lister, explorer ou copier/extraire des fichiers sur son PC.
---

# /everything — fichiers du PC via Everything

L'utilisateur tape `/everything <demande en langage naturel>`. Les outils viennent du serveur MCP `everything` (préfixe `mcp__everything__`). S'ils sont différés, les charger en un seul appel ToolSearch : `select:mcp__everything__everything_search,mcp__everything__everything_show,mcp__everything__everything_find_content,mcp__everything__everything_folder_info,mcp__everything__everything_copy`.

## Garde-fou absolu

**Interdit de déplacer, renommer, supprimer ou écraser un fichier ou un dossier** — ni avec ces outils, ni avec Bash/PowerShell (`mv`, `rm`, `rmdir`, `del`, `ren`, `Move-Item`, `Remove-Item`, `Rename-Item`, `robocopy /MOV /MOVE /MIR /PURGE`, `Copy-Item -Force` sur un fichier existant…). Si l'utilisateur le demande, refuser en une phrase et proposer une copie à la place. Toute duplication passe par `everything_copy`, jamais par une commande shell.

## 1. Traduire la demande

- Syntaxe Everything **en anglais** ; dates **toujours ISO** : « plus récent que le 1er janvier 2020 » → `dm:>=2020-01-01`.
- Dossier : `"D:\Chantiers\"` (avec antislash final, entre guillemets) = tout ce qui est dessous.
- Cas inhabituels : lire `C:\Users\pmaubert\dev\everything_mcp\docs\everything-syntax-1.4.md`.

## 2. Choisir l'outil

| Demande | Outil |
|---|---|
| trouver / lister des fichiers ou dossiers par nom, extension, date, taille | `everything_search` |
| « montre », « affiche », « ouvre dans Everything » | `everything_show` |
| « que contient ce dossier », taille, types de fichiers d'un dossier | `everything_folder_info` |
| un critère porte sur le **contenu** (« contenant », « qui mentionne ») | `everything_find_content` |
| « copie », « extrais », « duplique », « sauvegarde dans » | recherche puis `everything_copy` |

- Recherche dans le contenu : **exiger un dossier**. S'il n'y en a pas dans la demande, demander lequel avant de lancer. Mettre l'expression exacte dans `phrase`, les autres critères (extension, date, dossier) dans `query`.
- Si 0 résultat : réessayer une requête moins restrictive (jokers `*`, moins de termes, `match_path`) avant de conclure.

## 3. Copier — toujours en deux temps

1. **Rechercher** les éléments à copier (`everything_search` ou `everything_find_content`).
2. **Résoudre la destination** : un chemin relatif (`extract/`) se résout depuis le dossier du projet courant (répertoire de travail de Claude Code) → chemin absolu Windows.
3. **Choisir le mode** : à plat par défaut ; `preserve_tree_from=<dossier racine>` si l'utilisateur veut « garder la structure / les sous-dossiers ». Le mode arborescence sert à des fichiers dispersés sous une racine commune ; copier un seul dossier à plat conserve déjà sa structure interne.
4. **Présenter l'aperçu** et **attendre une confirmation explicite** :
   - nombre de fichiers et taille totale (dossiers : utiliser `everything_folder_info` pour les compter) ;
   - les 20 premiers éléments ;
   - destination absolue et mode ;
   - fichiers non vérifiés (`unverified`) et correspondances `method: "raw"` (moins fiables), s'il y en a.
5. Après le « oui » : appeler `everything_copy` avec les chemins absolus.
6. **Rendre compte** : nombre copié, volume, éléments ignorés (`skipped`) et erreurs, chemin du `manifest.csv`. Signaler explicitement à l'utilisateur, s'ils sont présents :
   - `errors[].target` : copie **partielle** laissée sur le disque à cet emplacement (indiquer le chemin) ;
   - `warnings` : copie complète, mais dates ou attributs non conservés ;
   - `manifest_error` : copie faite mais **non consignée** dans `manifest.csv`.

Pour copier des résultats de recherche : chercher avec `file:` ou passer des dossiers entiers uniquement, jamais un dossier avec son contenu (les éléments déjà inclus dans un dossier listé sont ignorés).

Des fichiers OneDrive « en ligne uniquement » dans un dossier à copier seront téléchargés : le signaler dans l'aperçu.

## Présentation des résultats

- Tableau compact : nom, dossier, taille lisible (Ko/Mo/Go), date de modification.
- Indiquer la requête Everything utilisée, sur une ligne.
- Beaucoup de résultats : afficher les 20 plus pertinents, proposer la suite (`offset`) ou `everything_show`.

## Si les outils sont introuvables ou en erreur

Everything doit être lancé (icône dans la zone de notification). Vérifier la connexion du serveur avec `/mcp`. Le dire simplement à l'utilisateur.
