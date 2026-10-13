# Syntaxe de recherche Everything 1.4 (référence)

Source : aide intégrée d'Everything 1.4 (version française). **Everything n'accepte que la syntaxe en anglais.**
Règle du projet : toujours écrire les dates au format ISO `AAAA-MM-JJ` (ex. `dm:>=2020-01-01`).

## Opérateurs

| Syntaxe | Effet |
|---|---|
| espace | ET |
| `\|` | OU |
| `!` | NON |
| `< >` | groupement |
| `" "` | expression exacte |

## Caractères de remplacement

| Syntaxe | Effet |
|---|---|
| `*` | zéro caractère ou plus |
| `?` | un seul caractère |
| `*.` | nom de fichier sans extension |
| `*.*` | nom de fichier et extension |

## Macros

`quot:` (") · `apos:` (') · `amp:` (&) · `lt:` (<) · `gt:` (>) · `#x:` (caractère Unicode de code x)

## Commutateurs

| Commutateur | Effet |
|---|---|
| `case:` / `nocase:` | casse respectée / ignorée |
| `diacritics:` / `nodiacritics:` | accents respectés / ignorés |
| `file:` / `folder:` | fichiers / dossiers uniquement |
| `nofileonly:` / `nofolderonly:` | lever la restriction fichiers / dossiers |
| `path:` / `nopath:` | comparer le chemin complet / le nom seul |
| `regex:` / `noregex:` | expressions régulières activées / désactivées |
| `wfn:` `wholefilename:` / `nowfn:` `nowholefilename:` | nom de fichier complet exigé / non |
| `ww:` `wholeword:` / `noww:` `nowholeword:` | mot entier / non |
| `wildcards:` / `nowildcards:` | jokers activés / désactivés |
| `ascii:` / `noascii:` `utf8:` | comparaisons rapides de casse ASCII activées / désactivées |

## Fonctions

| Fonction | Effet |
|---|---|
| `album:` `artist:` `comment:` `genre:` `title:` `track:` | métadonnées des médias |
| `attrib:` `attributes:<attributs>` | attributs (voir constantes plus bas) |
| `attribdupe:` `dadupe:` `dcdupe:` `dmdupe:` `dupe:` `namepartdupe:` `sizedupe:` | doublons (attributs, dates, nom, partie de nom, taille) |
| `bitdepth:` `dimensions:<l>x<h>` `width:` `height:` `orientation:landscape\|portrait` | images |
| `child:<nom>` | dossiers contenant un descendant de ce nom |
| `childcount:` `childfilecount:` `childfoldercount:` | nombre d'éléments d'un dossier |
| `content:` `ansicontent:` `utf8content:` `utf16content:` `utf16becontent:` | texte dans le contenu brut des fichiers (lent ; inopérant sur xlsx/docx/pptx compressés, non fiable sur xls/pdf) |
| `count:<max>` | nombre maximal de résultats |
| `da:` `dateaccessed:` | date d'accès |
| `dc:` `datecreated:` | date de création |
| `dm:` `datemodified:` | date de modification |
| `dr:` `daterun:` | date d'exécution |
| `rc:` `recentchange:` | date de changement récent |
| `empty:` | dossiers vides |
| `startwith:` `endwith:` | début / fin du nom (extension incluse) |
| `ext:<liste>` | extensions séparées par `;` |
| `filelist:<nom1\|nom2>` `filelistfilename:<nom>` | listes de fichiers |
| `frn:` `fsi:` | numéro de référence / index de système de fichiers |
| `infolder:<chemin>` `parent:<chemin>` | dans ce dossier, sous-dossiers exclus |
| `len:` | longueur du nom |
| `parents:<n>` | nombre de dossiers parents |
| `root:` | éléments sans dossier parent |
| `runcount:` | nombre d'exécutions |
| `shell:<nom>` | dossier système connu (sous-dossiers inclus) |
| `size:` | taille |
| `type:` | type de fichier |

## Syntaxe des fonctions

`fn:valeur` (égal) · `fn:=valeur` · `fn:<valeur` · `fn:<=valeur` · `fn:>valeur` · `fn:>=valeur` · `fn:début..fin` (plage)

## Tailles

`size:<n>[kb|mb|gb]`, ex. `size:102kb`, `size:>=50mb`.

| Constante | Plage |
|---|---|
| `empty` | vide |
| `tiny` | 0 – 10 Ko |
| `small` | 10 – 100 Ko |
| `medium` | 100 Ko – 1 Mo |
| `large` | 1 – 16 Mo |
| `huge` | 16 – 128 Mo |
| `gigantic` | > 128 Mo |
| `unknown` | inconnue |

## Dates

Formats : `AAAA`, `AAAA-MM`, `AAAA-MM-JJ`, `AAAA-MM-JJThh:mm:ss` (aussi `AAAAMMJJ…`). Les formats `mois/année` et `jour/mois/année` existent mais sont ambigus : ne pas les utiliser.

Exemples : `dm:>=2020-01-01`, `dm:2024-01-01..2024-06-30`, `dc:2025-07-11T13:29`, `size:huge dm:last2weeks`.

Constantes : `today`, `yesterday`, `tomorrow`, `unknown` ;
`<last|past|prev|current|this|coming|next><year|month|week>` (ex. `thisyear`, `lastmonth`) ;
`<last|past|prev|coming|next><x><years|months|weeks|days|hours|minutes|mins|seconds|secs>` (ex. `last3days`) ;
mois (`january`… / `jan`…) et jours (`monday`… / `mon`…).

## Constantes d'attributs (`attrib:`)

| Lettre | Attribut |
|---|---|
| A | archive |
| C | compressé |
| D | répertoire |
| E | chiffré |
| H | caché |
| I | non indexé par contenu |
| L | point d'analyse |
| N | normal |
| O | déconnecté (offline) — ex. `!attrib:O` pour exclure les fichiers non présents en local |
| P | fichier dispersé |
| R | lecture seule |
| S | système |
| T | temporaire |
| V | lecteur |

## Expressions régulières (avec `regex:`)

S'appliquent au **nom** du fichier (ou au chemin avec `path:`), pas au contenu.

| Syntaxe | Effet |
|---|---|
| `a\|b` | a ou b |
| `gr(i\|o)s` | « gris » ou « gros » |
| `.` | un caractère quelconque |
| `[abc]` / `[^abc]` | un caractère parmi / hors de a, b, c |
| `[a-z]`, `[a-zA-Z]` | plage de caractères |
| `^` / `$` | début / fin du nom |
| `( )` | sous-expression |
| `\n` | rappel de la n-ième sous-expression (1–9) |
| `\b` | limite de mot |
| `*` `?` `+` | 0+, 0–1, 1+ fois l'élément précédent |
| `*?` `+?` | versions paresseuses (le moins possible) |
| `{x}` `{x,}` `{x,y}` | x fois, x fois ou plus, entre x et y fois |
| `\` | échappement |
