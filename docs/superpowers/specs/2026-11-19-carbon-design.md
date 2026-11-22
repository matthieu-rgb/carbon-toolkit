---
title: "Conception - CARBON, banc offensif véhicule conteneurisé avec couche IA branchable"
type: design
statut: en revue
auteur: Matthieu Broquard
date: 2026-11-19
source: automotive-pentest-toolkit-requirements.md (exigences v0.1)
tags: [automotive-security, can, automotive-ethernet, uds, docker, mcp, ia, design, projet/carbon]
---

# CARBON — Document de conception

> [!info] Objet
> Ce document transforme les exigences v0.1 (`automotive-pentest-toolkit-requirements.md`) en une
> conception dont un dev compétent du domaine peut partir sans revenir vers l'auteur. Il fige
> l'intention, les frontières, l'architecture retenue, les décisions de « comment », et ce qui
> reste à l'appréciation du constructeur. Il doit être **validé** avant toute ligne de code.

---

## 1. Intention et pourquoi

Les outils de sécurité automobile (`can-utils`, Scapy/ISO-TP, `udsoncan`, CANalyzat0r, vehsec,
CANToolz, outils Wi-Fi/BLE) existent mais sont éparpillés : chacun s'installe à sa façon et
suppose que l'opérateur sait déjà où il en est dans sa démarche. **CARBON** (Car Offensive Bench,
nom provisoire) comble ce vide : un seul environnement Docker reproductible et jetable — « un
Exegol pour la voiture » — qui **intègre** les meilleurs outils (sans les réécrire) et ajoute
par-dessus une **couche de pilotage** qui situe en permanence l'opérateur dans la surface
d'attaque du véhicule.

Nouveauté structurante de cette conception par rapport aux exigences v0.1 : CARBON expose son
cœur comme un **serveur MCP** (Model Context Protocol), ce qui rend la couche de pilotage
**pilotable par n'importe quelle IA** — modèle local (Ollama, llama.cpp) ou frontière (Claude,
GPT) — sans que CARBON embarque ni n'impose aucun modèle. Le périmètre réseau est aussi élargi au
**CAN et à l'Automotive Ethernet** (DoIP, et SOME/IP en extension).

### Pourquoi ce choix d'architecture
La dernière intégration IA d'Exegol valide la direction : Exegol **n'embarque aucun modèle**, il
publie un serveur MCP (`pipx install exegol-mcp`) auquel n'importe quel client IA se connecte, et
expose deux familles d'outils (orchestration de conteneurs + exécution dans le conteneur via
`execute_command_in_container`). CARBON reprend ce découplage « capacités exposées / cerveau
branché par-dessus » — c'est exactement la « règle d'or » des exigences (section 6 : pilotage ≠
outils) — et va un cran plus loin en exposant **aussi la méthodologie**, pas seulement les outils.

---

## 2. Objectifs, non-objectifs, anti-objectifs

### 2.1 Objectifs (repris et mesurables)
| # | Objectif | Indicateur |
|---|---|---|
| O1 | Démarrage sans friction | Environnement opérationnel < 5 min sur machine Docker vierge |
| O2 | Couverture CAN/UDS de référence | Opérations CAN/UDS courantes faisables sans quitter CARBON |
| O3 | Reproductibilité | Deux installations → environnement identique (image versionnée) |
| O4 | Pédagogie | Un débutant sait quoi faire ensuite à chaque étape du mode Guidé |
| O5 | Portabilité terrain | Même image sur portable x86 et Raspberry Pi (ARM) |
| O6 | IA branchable, model-agnostic | Un modèle local **et** un modèle frontière pilotent une session via MCP, sans changement de code CARBON |
| O7 | Deux UI, un seul cœur | TUI et Web offrent les mêmes actions, toute la logique écrite une seule fois (couche partagée) |

### 2.2 Non-objectifs (v1 ; réévalués plus tard)
- Réécriture d'outils existants : **on intègre, on ne refait pas**.
- Analyse de firmware binaire avancée (reverse ECU) — candidat v2.
- Interface mobile native.
- Agent IA embarqué « clé-en-main » (voir §4, extension C) — **pas dans le cœur v1**.

### 2.3 Anti-objectifs (ce qui rendrait le projet un échec même s'il « marche »)
- Un énième agrégat d'outils sans la couche qui situe l'opérateur → on n'apporte rien.
- Une couche de pilotage qui contient de la logique d'outil, ou des outils qui contiennent de la
  méthodologie → le découplage est cassé, on ne peut plus faire évoluer l'un sans l'autre.
- Un produit lié à un seul modèle d'IA → trahit O6.
- Toute capacité pensée pour un usage non autorisé sur un véhicule tiers.

---

## 3. Contraintes

- **Hôte Linux** fournissant SocketCAN (modules `can`, `can_raw`, `vcan`). Le matériel d'interface
  (adaptateur CAN, antenne) est fourni par l'opérateur.
- **Multi-architecture** x86_64 **et** ARM64, même base d'outils (image unique multi-arch).
- **Moindre privilège** : pas de `--privileged` global par défaut ; accès matériel ciblé.
- **Solo-dev** : un seul développeur principal → le phasage strict est une contrainte de survie du
  projet, pas un confort (risque n°3 des exigences).
- **Licences amont** : l'intégration d'outils tiers impose un audit de compatibilité de licences.
- L'opérateur travaille sur un véhicule/banc dont il a **l'autorisation de test**.

---

## 4. Approches considérées

Trois façons de brancher l'IA sur le cœur ont été évaluées (voir conversation de cadrage) :

- **A — Tout-MCP (clone d'Exegol).** Un serveur MCP expose outils + méthodologie (ressources/prompts
  MCP). Léger, mais la méthodo n'est qu'un *conseil* (le modèle peut partir hors-piste même en
  Guidé), pas d'état de progression fiable, et dépend du support inégal des « resources/prompts »
  par les clients. → **Rejeté comme cœur** (reste un sous-ensemble utilisable comme MVP).
- **B — Moteur de méthodologie déterministe + outils, IA par-dessus.** La couche de pilotage est un
  vrai composant (arbre d'attaque YAML, état, progression) séparé des outils ; les deux sont
  exposés en MCP. Méthodo déterministe et testable, survit à un petit modèle médiocre, les deux
  modes (Guidé/Libre) en tombent naturellement. → **Retenu comme cœur v1.**
- **C — Agent IA embarqué + MCP.** CARBON embarque sa propre boucle d'agent (backend configurable)
  pour marcher sans client tiers. Plus lourd (harnais d'agent, prompts, adaptateurs par modèle),
  contre le « on ne refait pas » et le risque solo-dev. → **Retenu comme extension cadrée
  (v1.x/v2), pas dans le cœur v1.**

### Décision : **B comme cœur, C comme extension** — et B rend C quasi gratuit
Parce que B expose tout via MCP, un agent embarqué (C) n'est **rien d'autre qu'un client MCP de
plus** branché sur le même serveur. Aucun dédoublement : l'agent embarqué tape sur la même surface
que Claude Desktop ou Cursor. L'opérateur a donc, sur une base unique, **trois usages au choix** :

1. **Sans IA** — pilotage manuel du moteur en TUI/Web (les modes marchent sans aucun modèle).
2. **Client externe** — Claude/GPT/Ollama branché via MCP.
3. **Agent embarqué** — boucle d'agent CARBON, clé-en-main (extension C).

### Décision interface : **TUI + Web**, deux clients fins sur le même cœur
Choix de l'auteur. Surcoût « deux UI » mitigé par l'architecture : toute la logique vit dans le
cœur, les UI n'affichent et n'envoient que des actions. Phasage : **TUI d'abord, Web juste après**,
les deux lisant le même moteur. Le Web porte la **carte de surface d'attaque** (exigence EF-21) et
reçoit un soin de présentation dédié (skill `frontend-design`).

---

## 5. Architecture cible

```
        CLIENTS (au choix de l'operateur)                 [sans IA : pilotage manuel]
   +------------------+------------------+------------------------+
   | TUI (terminal)   | Web (navigateur) | Client MCP externe     |   AGENT EMBARQUE (ext. C)
   | Textual/Rich     | FastAPI + front  | Claude Desktop, Cursor |   boucle d'agent CARBON
   +--------+---------+--------+---------+-----------+------------+   backend configurable
            |  API interne     |             |  MCP (HTTP+token)      |  (= un client MCP de plus)
            v  (coeur en proc) v             v                        v
   +=================================================================================+
   |                              COEUR CARBON                                       |
   |  +---------------------------+     +--------------------------------------+     |
   |  | MOTEUR DE METHODOLOGIE    |     | REGISTRE D'OUTILS (adaptateurs)      |     |
   |  | arbre d'attaque YAML,     |<--->| can_sniff, can_replay, can_inject,   |     |
   |  | etat de session, position |     | isotp, uds_scan, read_dtc, clear_dtc,|     |
   |  | progression, suggestions  |     | seed_key, dbc_decode, doip_discover  |     |
   |  +---------------------------+     +--------------------------------------+     |
   |  +---------------------------+     +--------------------------------------+     |
   |  | JOURNAL / AUDIT (EF-23,   |     | SERVEUR MCP (HTTP localhost + token) |     |
   |  | ENF-21) + RAPPORT (EF-50) |     | expose outils + methodologie + etat  |     |
   |  +---------------------------+     +--------------------------------------+     |
   +=================================================================================+
                                   |
                       COUCHE ACCES MATERIEL
             SocketCAN (can0 / vcan0), USB passthrough, DoIP/IP
                                   |
   +-------------------------------+-------------------------------+
   | Hote x86 (adaptateur CAN) | Raspberry Pi ARM (sonde) | CAN virtuel (labs) |
   +---------------------------+--------------------------+--------------------+
```

**Règle d'or (inviolable) :** le moteur de méthodologie ne contient aucun outil, le registre
d'outils ne contient aucune méthodologie. On peut remplacer l'un sans casser l'autre.

### 5.1 Le cœur
Bibliothèque Python unique, utilisée en-process par la TUI et le Web, et exposée par le serveur
MCP. Responsabilités : état de session, position dans la surface d'attaque, exécution d'outils via
adaptateurs, journal, génération de rapport.

### 5.2 Moteur de méthodologie (déclaratif)
L'arbre d'attaque est décrit en **YAML** (décision : déclaratif, pour la contribution externe —
question ouverte §11 des exigences tranchée ici). Chaque étape déclare : objectif, outil mobilisé,
résultat attendu, **conditions machine-évaluables** sur le résultat, et étapes suivantes possibles
(une ou plusieurs). Le moteur lit ces données ; il ne code pas la méthodo en dur. Couverture
minimale v1 (EF-13) : accès CAN, découverte UDS, lecture DTC, sessions diagnostiques, seed-key.

**Qui interprète et fait avancer (décision, résout une tension de l'approche B) :** le moteur est
l'autorité de l'avancement, mais en deux temps :
- Il **évalue déterministiquement** les conditions YAML contre la **sortie structurée** de
  l'adaptateur (§5.3). Quand une seule branche est satisfaite, il peut auto-avancer ; l'état de
  progression reste donc fiable et testable **sans IA** (c'est ce qui fait « survivre à un modèle
  médiocre »).
- Quand plusieurs branches sont possibles ou qu'aucune condition n'est tranchée, le moteur
  **propose** les étapes candidates et laisse l'**opérateur ou l'IA choisir** ; le choix est
  journalisé. L'IA interprète et explique, mais ne redéfinit jamais la carte.

Conséquence directe : l'avancement et la **position sur la carte** (EF-21, mode Libre) reposent sur
le **contrat de sortie structurée** des adaptateurs, pas sur du parsing libre. C'est pourquoi ce
contrat (§5.3) est un livrable de premier plan, pas un détail.

#### 5.2.1 Périmètre v0.4 — Mode Guidé (moteur YAML + état persistant + TUI, décision auteur 2026-11-22)

La v0.4 **remplit** la surface « méthodologie/état » laissée creuse en v0.3 (§5.4.1) : un vrai moteur
de méthodologie déterministe, une méthodo v1 en YAML couvrant les **étapes 1→6** (§7) jouable
**sans matériel sur l'ECU simulée** (AC-07), les deux modes **Guidé/Libre** avec bascule sans perte
d'état, et la **TUI Textual** par laquelle un débutant « boucle un parcours » (AC-04). Model-agnostic :
tout marche **sans IA** (l'opérateur choisit) ; l'IA, si branchée via MCP, interprète et explique mais
**ne redéfinit jamais la carte**.

**Schéma YAML de l'arbre d'attaque.** Fichier déclaratif, versionné dans le dépôt (contribution
externe, ENF-30). Une liste d'**étapes** ; chaque étape déclare :
- `id` (stable), `title`, `objective` (texte pédagogique affiché) ;
- `tool` : nom d'un **adaptateur du registre** + paramètres par défaut (le moteur ne contient aucun
  outil — règle d'or ; il référence par nom) ; une étape purement informative (ex. « brancher
  l'OBD-II / attacher `vcan0` ») peut n'avoir **aucun** `tool` et avancer sur acquittement ;
- `expected` : texte « ce qu'on attend » ;
- `conditions` : **prédicats machine-évaluables** sur le `ToolResult` (voir ci-dessous) qui, vrais,
  rendent l'étape *satisfaite* ;
- `next` : une ou plusieurs étapes candidates (ids).

**Langage de conditions (décision — minimal, déclaratif, sûr, testable).** Pas de code arbitraire :
une condition est un petit prédicat sur `ToolResult.to_dict()` parmi un jeu fermé —
`ok` (booléen), `equals(path, valeur)`, `contains(path, valeur)` (listes/chaînes), `exists(path)`,
`truthy(path)` — où `path` adresse `data.<clé>` (p. ex. `contains(data.supported, "0x27")`,
`equals(data.cleared, true)`). Combinables en `all`/`any`. Le moteur évalue ces prédicats contre la
**sortie structurée** de l'adaptateur (le contrat §5.3), jamais par parsing de texte libre.

**Moteur (autorité d'avancement, en deux temps — reprend §5.2).** Après l'exécution d'une étape, il
évalue les `conditions` des candidats `next` : si **une seule** branche est satisfaite → **auto-avance** ;
si **plusieurs** ou **aucune** ne tranche → il **propose** les candidats et laisse l'**opérateur ou
l'IA choisir** ; le choix est **journalisé**. L'état de progression est donc fiable et testable
**sans IA**.

**État persistant + reprise (EF-14, décision).** L'état de session — méthodo chargée, étape courante,
historique (étapes franchies + `ToolResult` associés), mode courant — est sérialisé en **JSON sur
disque** (à côté du journal), **repris** au redémarrage. La `Session` (v0.3) gagne cette intégration
moteur ; `session_state()` (surface MCP) renvoie désormais la méthodo chargée + l'étape courante +
les candidats au lieu de « libre/none ».

**Deux modes et bascule (EF-21/22/24).** **Guidé** : le moteur tient le fil et impose l'ordre ;
**Libre** : accès direct à tous les outils, le moteur **trace** la position sur la carte (§7) et
**suggère** de façon non bloquante. Bascule **Guidé ↔ Libre sans perte d'état**.

**Méthodo v1 (étapes 1→6) jouable sur l'ECU simulée.** 1 ACCÈS (attacher `vcan0`, informatif) →
2 RECONNAISSANCE CAN (`can_sniff`/`can_dump`) → 3 DIAGNOSTIC UDS (`uds_scan`, `uds_session`) →
4 DTC & DONNÉES (`uds_read_dtc`, `uds_read_did`, `uds_clear_dtc` **destructif**) → 5 SEED-KEY
(`uds_security_access`) → 6 REJEU & INJECTION (`can_replay`, `can_inject` **destructifs**). Les
étapes destructrices passent par le **garde-fou v0.3** (`pending-approval`).

**TUI (Textual, décision interface §interface).** Client **fin** dans **le même processus** que la
`Session`/serveur MCP (état partagé §5.4) : elle n'affiche et n'envoie que des actions. Elle montre
l'étape courante (objectif, outil suggéré), exécute l'outil, affiche le **résultat structuré** et son
interprétation, puis auto-avance ou présente les choix ; en Libre elle montre la **position sur la
carte** et les suggestions ; les actions destructrices demandées **apparaissent pour approbation dans
la TUI** (façade sur la file `pending-approval` de v0.3 — ce que le design visait §5.4). La TUI est
une **façade** : toute la logique vit dans le moteur/cœur, écrite une seule fois (O7).

**Précisions d'implémentation (levée d'ambiguïtés, relecture builder 2026-11-22) :**

- **Contrat du moteur (lève une contradiction de ma 1re rédaction) — modèle unique.** Les
  `conditions` d'une étape sont des **post-conditions sur SON PROPRE `ToolResult`** (l'étape a-t-elle
  atteint son objectif ?). Le **choix de branche** se fait par un prédicat optionnel **`when`** porté
  par chaque arête de `next`, évalué contre le **résultat qui vient d'être produit** : le moteur
  avance vers le candidat dont le `when` est vrai (ou l'unique `next` sans `when`) ; si **0 ou >1**
  `when` sont vrais → il **propose** et l'opérateur/IA **choisit** (journalisé). Une étape dont les
  post-conditions échouent est « non satisfaite » : le moteur l'affiche et propose les candidats de
  remédiation (ex. accès refusé `ok=False`+`data.nrc` → l'arête `when` qui matche route vers l'étape
  seed-key). *Un seul moteur, pas deux.*
- **Grammaire des conditions — fermée et plate.** `ok` (top-level) + `equals(path, v)` /
  `contains(path, v)` / `exists(path)` / `truthy(path)`, combinables en `all`/`any`. `path` adresse
  **un seul niveau sous `data`** (`data.<clé>`) — **pas d'indexation ni de JSONPath profond**. Les
  champs-listes se testent par `truthy`/`exists`/`contains(scalaire)` (ex. `truthy(data.dtcs)` = « ≥1
  DTC » ; `contains(data.supported, "0x27")` ; `equals(data.cleared, true)` ; `equals(data.unlocked,
  true)`). Suffit aux étapes 1→6 ; trivial et sûr à évaluer.
- **Approbation destructrice quand la TUI tourne (résout le conflit de threads v0.3).** La TUI tient
  le terminal et sa propre boucle asyncio ; **sous TUI, le thread console stdin de v0.3 n'est PAS
  démarré** — **la TUI est la surface d'approbation**. `ApprovalQueue` gagne un **hook de
  notification** ; la TUI s'y abonne et présente une **modale** pour toute action `pending-approval`.
  Nouvel **`Origin.TUI`** pour une action destructrice déclenchée **par l'humain dans la TUI** :
  approuvée par la **modale TUI** (jamais `input()`, jamais la file de l'IA). Un serveur MCP HTTP
  embarqué (optionnel, pour le pilotage IA) tourne **uvicorn dans un thread de fond** ; une action
  destructrice venue de l'IA **apparaît dans la même modale TUI**. L'appel bloquant (`Event`) est
  déporté sur un worker pendant que la modale tranche.
- **Nouvelles actions (TUI + outils MCP).** `methodology_load(path)`, `mode_set(guided|libre)`,
  `step_ack()` (acquitter une étape informative sans `tool`), `step_choose(step_id)` (trancher un
  embranchement). Exposées comme **outils MCP** (pour l'IA) et touches/commandes TUI (pour l'humain).
- **Guidé impose l'ordre ; Libre trace.** En **Guidé**, exécuter un outil qui n'est ni l'étape
  courante ni un candidat est **refusé** (retour informatif, non destructif) — le moteur garde le
  débutant sur les rails (§5.5 « impose l'ordre »). En **Libre**, tout outil passe ; le moteur
  **trace** la position **au mieux** = l'étape de plus haut rang dont l'outil correspond au dernier
  outil joué (indicatif, non autoritaire). Exécuter l'outil de l'étape courante déclenche
  l'évaluation + auto-avance/proposition.
- **Moteur ↔ Session / chemin unique.** Le moteur est un **composant porté par la `Session`** ;
  `run_tool` **continue de passer par `execute_tool`** (chemin unique v0.3) puis **pousse** le
  `ToolResult` au moteur (Guidé : évalue+avance ; Libre : trace). Le moteur **construit les kwargs de
  `run()` de l'adaptateur** (donc étape 6 `can_inject` utilise `data`=octets, **pas** le `data_hex`
  du wrapper MCP). Règle d'or : le moteur ne contient aucun outil (référence par nom via le registre).
- **Paramètres d'étape & étape informative.** Une étape peut marquer un paramètre `prompt: true`
  (saisi au **runtime** : formulaire TUI / argument MCP) vs valeur par défaut (indispensable pour
  étape 6 `can_inject`, souvent pour `uds_read_did`). Une étape **sans `tool`** s'acquitte par
  `step_ack` (événement journalisé) ; ses post-conditions sont vacueusement satisfaites et le choix de
  `next` se fait par `when`/manuel.
- **Persistance & reprise (EF-14).** Fichier **JSON** à côté du journal (`carbon-session.state.json`),
  écrit par **remplacement atomique** à chaque transition : méthodo chargée + étape courante + mode +
  historique (étapes franchies + `ToolResult`). La reprise restaure la **position de méthodologie,
  pas l'état vivant de la cible** : l'ECU simulée (process séparé) a pu redémarrer/re-verrouiller — le
  moteur **ne suppose pas** que les prérequis (déverrouillage) tiennent encore ; rejouer l'étape les
  rétablit. (Distinct de `Session.history`, le tampon runtime plafonné.)
- **Bascule sans perte d'état (EF-24).** `mode` est un **toggle runtime** (touche TUI + `mode_set`) ;
  la bascule **conserve le pointeur d'étape verbatim** (pas de recalcul), donc pas de perte d'état ni
  de ré-invocation du mapping indicatif.
- **Portée Libre v0.4 vs v0.5.** v0.4 (TUI) = **position textuelle + suggestions non bloquantes**,
  **pas** de carte visuelle ; AC-05 (« affiche la position et journalise ») est une cible **v0.4** en
  forme textuelle. La **carte visuelle** et le **Web** restent v0.5.
- **Tests TUI sans tête.** `App.run_test()` / `Pilot` (Textual) ; le harnais v0.4 monte **TUI +
  Session + ApprovalQueue dans un seul process** et exerce la navigation, l'auto-avance **et ≥1
  parcours d'approbation destructrice via la modale TUI**. (Pas de workflow GitHub Actions ajouté en
  v0.4 — infra séparée ; les tests tournent via `pytest` comme aujourd'hui.)
- **Validation YAML (ENF-30).** Chargement **fail-fast** : adaptateur `tool` inconnu, `next` pointant
  un id absent, ou YAML malformé → erreur claire au chargement, pas en cours de parcours.

**Hors périmètre v0.4** (pour éviter la dérive) : **Web** (v0.5), **rapport** de session (v1.0),
**matériel OBD-II réel** (v0.4 tourne sur `vcan0`/ECU simulée ; le branchement réel est documenté,
AC-12), Automotive Ethernet/DoIP, agent embarqué (ext. C).

### 5.3 Registre d'outils (adaptateurs)
Chaque outil intégré est encapsulé par un **adaptateur** à interface uniforme (entrées validées,
sortie structurée, code de retour, artefacts/captures). Déclaration **déclarative et documentée**
d'un nouvel outil (ENF-30). Les adaptateurs appellent les outils amont (`python-can`, `can-utils`,
`udsoncan`, Scapy, etc.) — ils ne les réécrivent pas.

### 5.4 Serveur MCP
Transport **HTTP sur `127.0.0.1` + token Bearer requis par défaut** (aligné sur Exegol), `stdio`
en option. Expose trois surfaces : **outils** (les adaptateurs), **méthodologie/état** (position,
étape courante, suggestions), et **ressources** (DBC, captures, rapport). Model-agnostic par
construction : le modèle est fourni par le client.

**Processus unique et état partagé (décision) :** le serveur MCP et les clients TUI/Web tournent
dans **le même processus** et partagent la **même instance de session/cœur**. L'« API interne »
de la TUI/Web et la surface MCP sont deux façades sur le même état vivant. C'est ce qui rend
possible le garde-fou destructif ci-dessous : une action demandée par l'IA via MCP peut être mise
en attente et apparaître **immédiatement** pour approbation dans la TUI/Web.

#### 5.4.1 Périmètre v0.3 — « premier pilotage par IA » (décision auteur 2026-11-22)

La v0.3 livre le **découplage** promis par l'approche B : n'importe quel client MCP pilote le cœur,
sans qu'aucun modèle ne soit embarqué. Elle est volontairement cadrée pour un socle testable et
indépendant, **avant** le moteur de méthodologie YAML (v0.4) et la TUI/Web (v0.4/v0.5).

**SDK & libs.** SDK MCP Python officiel (`mcp`, épinglé **`mcp==2.3.0`** ; API 2.x `MCPServer` — `FastMCP` était le nom 1.x), vérifié par test
comme on l'a fait pour `udsoncan`/`can-isotp` (ne jamais supposer une API ; l'implémenteur inspecte
la version installée, l'épingle, et prouve par test). On **enveloppe** le SDK, on ne le réécrit pas
(règle d'or). Le serveur MCP ne contient aucune méthodologie et n'appelle les outils **que** par le
registre d'adaptateurs existant (aucun chemin d'exécution parallèle à la CLI).

**Trois surfaces, dont une encore creuse à ce jalon :**
- **Outils** — les **10 adaptateurs existants** (`can_sniff`, `can_dump`, `can_replay`,
  `can_inject`, `uds_scan`, `uds_session`, `uds_security_access`, `uds_read_did`, `uds_read_dtc`,
  `uds_clear_dtc`) exposés en outils MCP. Entrées validées aux frontières, **sortie structurée**
  (le `ToolResult`), paramètres dérivés des mêmes options que la CLI. L'IA pilote **exactement** ce
  que la CLI pilote — ni plus, ni moins.
- **État/session** — position/journal/derniers résultats/liste d'outils disponibles, lus sur la
  **même instance de session** que la CLI. La surface **méthodologie reste « aucune chargée / mode
  libre »** jusqu'au moteur YAML (v0.4) ; elle existe mais ne propose pas d'étapes.
- **Ressources** — export du **journal/rapport** de session (lecture seule).

**Garde-fou destructif (le livrable sécurité central de v0.3, comble le trou d'Exegol MCP).** Un
appel d'outil **destructif** d'**origine MCP** (p. ex. `uds_clear_dtc`) **n'exécute jamais
directement** : il entre dans une **file d'approbation** en mémoire (état `pending-approval` +
identifiant court), **bloque** l'appel MCP, et n'exécute qu'après approbation **humaine explicite**.
Le `--yes` de la CLI (confirmation pour un appel **humain direct**) est **ignoré pour toute origine
MCP** : l'IA détient le token, elle s'auto-accorderait sinon et viderait la garantie. L'**origine**
de l'appel (CLI humaine vs MCP) est donc un attribut de premier plan porté jusqu'au garde-fou.

**Canal d'approbation = hors du pipe MCP (décision).** L'approbation passe par un canal que
**l'IA ne peut pas atteindre** :
- **Mode HTTP + token Bearer** (`127.0.0.1`) — déploiement « réel » : la **console du serveur** est
  libre, donc elle **porte l'approbation** (invite sur le terminal contrôlant le serveur, ou
  commande locale listant/approuvant la file). C'est le mode qui tient l'exigence roadmap « auth
  token » **et** les actions destructrices approuvées. C'est aussi le mode du scénario réseau
  (sonde Pi).
- **Mode stdio** (console = pipe du protocole) — pratique pour les clients type Claude Desktop :
  sert les outils **non destructifs** et **refuse** le destructif (`pending-approval` impossible
  faute de canal humain), avec une erreur claire. Transport ↔ capacité liés proprement, **sans IPC
  inter-processus** à introduire à v0.3.
- La machine pending-approval construite ici est l'**autorité partagée** ; la TUI/Web (v0.4) ne
  fait qu'ajouter une **façade** d'approbation sur la même file, elle ne la réinvente pas.

**Validation O6 (« un modèle local ET un frontière pilotent une session »).** Prouvée en CI **sans
modèle ni réseau** par un **client MCP en mémoire** (fourni par le SDK) : il liste les outils, en
exécute un non destructif (p. ex. `uds_scan` contre l'ECU simulée sur CAN virtuel), lit l'état, et
vérifie qu'un outil destructif passe en `pending-approval` puis s'exécute après approbation
simulée. Le pilotage réel par **Ollama (local)** et par **Claude (frontière)** est un **check manuel
documenté** (comme `vcan0`/buildx le sont pour v0.1/v0.2), hors CI.

**Hors périmètre v0.3** (confirmé, pour éviter la dérive) : moteur de méthodologie YAML et étapes
(v0.4), TUI/Web (v0.4/v0.5), OAuth MCP (le token Bearer suffit v1, ENF-sécurité §7), surfaces
DBC/captures riches (v0.5+), agent embarqué (ext. C).

**Précisions d'implémentation (levée d'ambiguïtés, relecture builder 2026-11-22) :**
- **Pas de démon, pas de commande `carbon approve` séparée, aucun IPC.** La **session** (cœur
  partagé) et la **file d'approbation** vivent dans le **process du serveur MCP**. La CLI historique
  reste un process **court et indépendant** qui ne partage que le **journal JSONL** sur disque.
  L'approbation d'une action `pending-approval` est une **invite sur la console contrôlant le
  serveur** (même process) — c'est ce que signifie « canal hors pipe MCP » à v0.3. La TUI (v0.4,
  **même** process que le serveur) ne fera qu'ajouter une **façade** d'approbation sur cette même
  file ; elle ne la réinvente pas. (Ceci lève la contradiction d'une file en mémoire approuvée
  depuis un second process.)
- **Modèle de concurrence du blocage.** Le serveur reste **réactif** pendant qu'un appel est en
  attente : les outils **non destructifs continuent de passer**, et la console d'approbation reste
  disponible (serveur multi-thread/async). L'appel destructif bloqué attend un **`threading.Event`
  indexé par l'identifiant** d'approbation. **Pas de blocage infini** : un **timeout** (défaut
  raisonnable, p. ex. 300 s) → **refus** (`ToolResult(ok=False)` « approbation expirée »), journalisé
  comme refus. Une approbation → exécution réelle + journal ; un refus explicite → `ToolResult`
  informatif, jamais d'exception.
- **Pipeline d'exécution partagé (règle « aucun chemin parallèle à la CLI »).** Le pipeline
  **garde-fou → `run()` → journal**, aujourd'hui inline dans `cli.py`, est **extrait** dans le cœur
  (fonction/méthode de session) que **les deux** appelants invoquent. Il porte un attribut
  **`origin` ∈ {CLI, MCP}** (et le transport pour MCP). `--yes` n'a d'effet que pour `origin=CLI` ;
  pour `origin=MCP`, un outil destructif part **toujours** en `pending-approval` (ou refus en
  stdio). L'`actor` du journal vaut **`"mcp"`** pour les appels MCP (contre `"cli"` aujourd'hui).
- **`channel` / `interface` / `journal` = configuration au lancement du serveur**, **pas** des
  paramètres par outil (ils sont des globals CLI posés une fois, pas des options par commande). La
  « session » MCP est donc liée à **un bus et un journal** fixés au démarrage ; les schémas d'outils
  ne les exposent pas.
- **Schémas d'outils MCP = surface CLI exposée, en types programmatiques.** Chaque wrapper d'outil
  déclare un schéma **typé et lisible par un modèle** (entiers pour les identifiants d'arbitrage,
  octets/hex documenté pour les charges utiles) — **source de vérité unique par outil**, découplée
  des callbacks `click` (ergonomie humaine) comme de la signature brute de `run()`. On expose **la
  surface que la CLI expose** (`_PARAMS`) : les kwargs non exposés (`rxid`/`txid`) **restent à leurs
  défauts** et n'apparaissent pas.
- **Ce que renvoient les surfaces état/ressources à v0.3.** La session garde en mémoire un
  **historique des derniers `ToolResult`** (ajout mineur) : c'est la base de « derniers résultats ».
  La surface **méthodologie/position** répond « aucune chargée / mode libre » (pas d'étape proposée
  tant que le moteur YAML n'existe pas, v0.4). La **ressource** est le **journal JSONL brut** en
  lecture seule (le moteur de **rapport** formaté est v1.0).

### 5.5 Les deux modes (sur le même cœur)
- **Guidé** : le moteur tient le fil, impose l'ordre des étapes ; l'IA (ou l'opérateur) interprète
  et explique. État de progression persistant et reprise (EF-14).
- **Libre** : accès direct à tous les outils, sans parcours imposé ; le moteur **trace** la
  position sur la carte et suggère de façon non bloquante (EF-21, EF-22).
- Bascule Guidé ↔ Libre sans perte d'état (EF-24).

### 5.6 Environnement simulé sans matériel (décision, résout AC-03 + AC-07)
AC-07 exige que **tout** fonctionne sur `vcan0` sans matériel, et AC-03 exige un **dialogue UDS
complet** (scan → session → DTC → seed-key). Or ICSim simule du trafic CAN mais **n'implémente pas
de serveur de diagnostic UDS/ISO-TP** : il ne répond pas aux requêtes UDS. CARBON embarque donc un
**ECU simulé** (répondeur ISO-TP/UDS léger) comme composant à part entière : il répond aux services
UDS, gère sessions, DTC (lecture/effacement) et une routine **seed-key d'exemple** (§8). C'est le
support de test de la couche UDS et la condition pour tenir AC-03 et AC-07 ensemble. Livré en
**v0.2** (voir roadmap). ICSim reste utilisé pour les labs de trafic CAN (EF-15).

#### 5.6.1 Périmètre v0.2 — « minimal mais réaliste » (Option A, décision auteur 2026-11-20)

Deux niveaux de réalisme ont été envisagés pour l'ECU simulée et la couche UDS : **A** (une ECU,
chemins nominaux **+** codes de réponse négative corrects **+** verrouillage par session/sécurité,
un seed-key d'exemple) et **C** (parc multi-ECU, niveaux de sécurité multiples, DID verrouillés
étendus, timing TesterPresent). **Décision : A pour v0.2** ; **C devient un jalon d'apprentissage
ultérieur** (progression pédagogique : A pour comprendre le dialogue, C pour s'entraîner sur un
parc plus fidèle — voir roadmap). La raison du choix de A : c'est le minimum pour que **sessions et
seed-key aient un sens réel** (un service réellement refusé tant qu'on n'est pas déverrouillé),
sans la sur-ingénierie d'un parc complet.

**Décisions de « comment » (calls auteur, à défaut de contre-indication) :**

- **Transport & client UDS** : côté *client* (adaptateurs CARBON), s'appuyer sur `can-isotp`
  (transport ISO 15765-2) + `udsoncan` (client UDS ISO 14229) — on **n'implémente pas** le protocole
  à la main. Côté *ECU simulée*, un **serveur maison** ISO-TP/UDS léger (udsoncan ne fournit pas de
  serveur), construit au-dessus de `can-isotp`. La règle d'or tient : les adaptateurs *enveloppent*
  la lib, l'ECU simulée est un **outil à part**.
- **Services UDS couverts (client + ECU)** :
  - `0x10` DiagnosticSessionControl — sessions *default* (`0x01`) / *extended* (`0x03`).
  - `0x3E` TesterPresent — maintien de session.
  - `0x27` SecurityAccess — requestSeed / sendKey, **un** niveau de sécurité.
  - `0x22` ReadDataByIdentifier — quelques DID, dont **un verrouillé** derrière la sécurité.
  - `0x19` ReadDTCInformation — lecture des DTC (`reportDTCByStatusMask`, sous-fonction `0x02`).
  - `0x14` ClearDiagnosticInformation — effacement DTC ; **action destructrice** → passe par le
    garde-fou `authorize` (comme inject/replay en v0.1).
  - **Scanner UDS** (`uds_scan`) — balaye les SID, distingue *supporté* / *NRC serviceNotSupported*
    (`0x11`), restitue la surface diagnostic.
- **Verrouillage (ce qui donne du sens au seed-key)** : la session *extended* est requise pour
  SecurityAccess (sinon NRC) ; le **DID protégé** et **ClearDTC** ne répondent qu'une fois le
  seed-key validé, sinon NRC *securityAccessDenied* (`0x33`) / *conditionsNotCorrect* (`0x22`).
  L'ECU renvoie les **NRC corrects** partout (service non supporté, sous-fonction invalide, séquence
  erronée, accès refusé).
- **Seed-key d'exemple (documenté, pas de la vraie crypto)** : l'ECU tire un seed 32 bits ; la clé
  attendue est une transformation **déterministe et documentée** (ex. `key = (seed XOR 0xA5A5A5A5)`
  avec rotation fixe), écrite noir sur blanc dans la doc pour que le débutant la reproduise. Branchée
  dans le framework seed-key enfichable (§8) comme algo de référence.
- **Adressage** : CAN 11-bit, **une** ECU — requête `0x7E0`, réponse `0x7E8` (convention OBD-II).
- **Sans matériel** : tout tourne sur `vcan0`. L'ECU simulée est un processus/thread attaché au même
  bus virtuel que les adaptateurs client (tient AC-07).

### 5.7 Connectivité physique au véhicule et antennes (demande explicite)
CARBON doit pouvoir se **brancher sur un vrai véhicule** et exploiter les **antennes** de
l'opérateur. La couche d'accès matériel couvre donc, par passthrough dans le conteneur :

- **Prise OBD-II → CAN.** Adaptateur OBD-II/CAN USB (type CANable/CANtact/USB-CAN, Wi-Fi
  intégrant SLCAN, ou interfaces natives SocketCAN). CARBON crée/attache `can0` côté hôte et aide à
  **identifier les bus** derrière la prise OBD-II (broches, plusieurs bus CAN possibles). Repli
  `vcan0` quand aucun matériel (ENF-04).
- **Automotive Ethernet / DoIP.** Accès IP vers le véhicule (via câble OBD-II→Ethernet/activation
  DoIP) ; `network=host` seulement si strictement requis et documenté (§6).
- **Antenne Wi-Fi USB** en **mode monitor** (audit infotainment) — passthrough du périphérique.
- **Dongle BLE USB** (clés, télématique) — passthrough.
- **SDR/RF USB** (télécommandes, sans contact) — passthrough, en extension (EF-42).

Décisions : accès par `--device`/`--cap-add` **ciblé par périphérique** (pas de `--privileged`
global, §6) ; les configurations matérielles validées (adaptateurs, antennes) sont **documentées**
(risque n°1 des exigences) ; le mode d'emploi (AC-12) couvre le branchement OBD-II réel **et** le
repli sans matériel. Le détail des modèles d'adaptateurs/antennes supportés et des règles udev est
laissé au constructeur, à partir de cette liste.

---

## 6. Sécurité et conformité (décisions explicites)

Le code sera écrit « proprement avec la sécurité appropriée » (demande de l'auteur). Décisions :

- **Moindre privilège** : jamais de `--privileged` global par défaut. Accès matériel ciblé via
  `--device`/`--cap-add` documenté par périphérique ; `network=host` seulement si strictement
  requis pour DoIP et documenté (ENF-20).
- **Authentification MCP** : token Bearer obligatoire par défaut, bind `127.0.0.1`. Le token est
  généré au lancement et stocké hors du dépôt. OAuth MCP non requis v1.
- **Confirmation des actions destructrices (protocole, corrige une faille du garde-fou)** : toute
  action pouvant modifier l'état d'un calculateur (injection CAN, `clear_dtc`, écriture UDS) passe
  par une **approbation humaine hors-bande**. Le flag `--yes` d'auto-confirmation n'est honoré que
  pour un appel **humain direct en CLI** ; il est **ignoré pour tout appel d'origine MCP** (sinon
  l'IA, qui détient le token, se l'auto-accorderait et viderait la garantie). Concrètement : une
  action destructrice demandée via MCP renvoie un état `pending-approval` et **bloque** jusqu'à ce
  qu'un humain l'approuve dans la TUI ou le Web (possible grâce au processus/état unique, §5.4).
  L'IA ne peut **jamais** déclencher une action destructrice sans cette approbation humaine (comble
  le manque de confirmation constaté chez Exegol MCP).
- **Journalisation/audit** : chaque action (humaine ou IA), horodatée, est journalisée pour
  reconstruire la session (EF-23, ENF-21). Le journal alimente le rapport (EF-50).
- **Avertissement d'usage autorisé** au premier lancement (ENF-22).
- **Validation des entrées** aux frontières (adaptateurs, API MCP, API UI) ; pas d'exécution shell
  non paramétrée à partir d'entrées non validées.
- **Secrets & vie privée** : aucune donnée de mission ni identité de l'opérateur envoyée à un
  service externe par CARBON lui-même. (Le choix d'un modèle frontière côté client sort du
  périmètre de CARBON mais est documenté comme avertissement, cf. Exegol.)
- **Cadre légal** : références ISO 21434 / UN R155 dans la doc (ENF-23).

---

## 7. Surface d'attaque couverte (base du mode Guidé)

```
1. ACCES PHYSIQUE      -> prise OBD-II, identification des bus CAN
2. RECONNAISSANCE CAN  -> sniff, cartographie trafic, identification ECU
3. DIAGNOSTIC UDS      -> scan services, sessions, niveaux de securite
4. DTC & DONNEES       -> lecture/effacement codes defaut, DID
5. SEED-KEY            -> acces sessions protegees (algos documentes)
6. REJEU & INJECTION   -> validation d'impact (avec confirmation)
7. AUTOMOTIVE ETHERNET -> DoIP (SOME/IP en extension)        [NOUVEAU vs v0.1]
8. SANS-FIL (v1.x)     -> Wi-Fi infotainment, BLE cle/telematique
9. RESTITUTION         -> rapport de session
```

---

## 8. Décisions de « comment » (prises ici)

| Sujet | Décision | Statut |
|---|---|---|
| Langage/stack | Python (`python-can`, Scapy, `udsoncan`, SDK MCP Python, Textual) | choix auteur |
| Moteur méthodo | Déclaratif YAML | choix auteur (tranche §11 exigences) |
| Transport MCP | HTTP localhost + token Bearer ; stdio optionnel | choix auteur (aligné Exegol) |
| Périmètre MCP/IA v0.3 | **10 adaptateurs existants en outils MCP + surface état/session + ressources journal** ; méthodo creuse jusqu'à v0.4 (§5.4.1). SDK `mcp==2.3.0` (API `MCPServer`) épinglé/vérifié par test. O6 prouvé en CI par client MCP en mémoire. | **validé auteur 2026-11-22** |
| Garde-fou destructif via MCP v0.3 | **File `pending-approval` bloquante** ; approbation **hors pipe MCP** (console serveur en mode HTTP+token) ; `--yes` ignoré pour origine MCP ; **stdio refuse le destructif** faute de canal humain (§5.4.1). | **validé auteur 2026-11-22** |
| Périmètre v0.4 Mode Guidé | **Moteur méthodo YAML** (étapes 1→6 sur ECU simulée) + **langage de conditions fermé** (prédicats sur `ToolResult`, pas de code arbitraire) + **état persistant/reprise** (JSON) + modes **Guidé/Libre** avec bascule sans perte d'état + **TUI Textual complète** (façade, même process). Remplit la surface méthodo/état MCP creuse en v0.3 (§5.2.1). | **validé auteur 2026-11-22** |
| Interfaces | TUI (Textual) + Web (FastAPI + front soigné `frontend-design`) | choix utilisateur |
| Phasage UI | TUI d'abord, Web juste après, même cœur | choix auteur |
| Agent embarqué (C) | Extension v1.x/v2, = client MCP de plus | choix utilisateur |
| Automotive Ethernet | DoIP remonté dans le périmètre (SOME/IP extension) | choix utilisateur |
| Seed-key v1 | **Framework seed-key enfichable + 1-2 algos d'exemple documentés** (pas de couverture OEM large, souvent propriétaire) ; l'ECU simulé embarque une routine correspondante pour les tests | choix auteur |
| ECU simulé | Répondeur ISO-TP/UDS embarqué (§5.6), livré v0.2 | choix auteur |
| Périmètre UDS v0.2 | **Option A** : 1 ECU, NRC corrects, verrouillage session/sécurité, 1 seed-key d'exemple (§5.6.1). **Option C** (parc multi-ECU) = jalon d'apprentissage ultérieur. | **validé auteur 2026-11-20** |
| Libs UDS v0.2 | Client : `can-isotp` + `udsoncan` (on enveloppe, on ne réécrit pas). ECU simulée : serveur ISO-TP/UDS maison sur `can-isotp`. | choix auteur |
| Distribution | **Image multi-arch préconstruite et signée publiée sur un registre (ex : GHCR)** = chemin d'install supporté, piloté par le wrapper CLI (tient AC-01 < 5 min) ; build local = chemin dev. **Le premier publish public est bloqué par l'audit des licences amont** (redistribution). | choix auteur |
| Licence | **GPLv3** (copyleft, compat. intégration GPL amont) | **validé auteur** (audit licences amont à faire avant 1er publish) |
| Portée offline | Air-gap = **config supportée**, pas une exigence dure v1 ; model-agnostic garantit l'offline via client local (Ollama) | **validé auteur** |
| CAN | Bibliothèque **`python-can`** comme accès CAN de référence | **validé auteur** |

---

## 9. Roadmap par jalons (révisée)

```
v0.1  SOCLE        Dockerfile multi-arch, acces CAN (can0/vcan0),
                   coeur minimal + registre d'outils, CLI, can-utils + Scapy
                   -> Critere : capture et rejeu CAN sur vcan0
v0.2  UDS          ISO-TP, scan UDS, DTC, seed-key documente,
                   + ECU SIMULE (repondeur ISO-TP/UDS, §5.6) -- Option A (§5.6.1)
                   -> Critere : dialogue UDS complet sur ECU simule (sans materiel)
v0.2+ LAB UDS      Option C (apprentissage) : parc multi-ECU, niveaux de securite
                   multiples, DID verrouilles etendus, timing TesterPresent
                   -> Critere : parcours UDS sur plusieurs ECU a adresses distinctes
v0.3  MCP + IA     Serveur MCP (outils + methodo + etat), auth token,
                   confirmation actions destructrices
                   -> Critere : un modele local ET un frontiere pilotent une session (O6)
v0.4  MODE GUIDE   Moteur de methodologie YAML, etapes 1 a 6, etat persistant, TUI
                   -> Critere : un debutant boucle un parcours CAN/UDS
v0.5  MODE LIBRE   Carte surface d'attaque, suggestions, journalisation, Web
                   -> Critere : bascule Guide <-> Libre sans perte d'etat
v1.0  RESTITUTION  Rapport de session exportable, doc + mode d'emploi, licence
                   -> Critere : rapport genere en fin de mission
v1.x  EXT.         Automotive Ethernet (DoIP) consolide, Wi-Fi/BLE, agent embarque (C)
v2+   EXTENSIONS   CAN-FD, SOME/IP, reverse firmware, PwnDoc, sonde Pi avancee
```

> Note : le MCP/IA est volontairement remonté en v0.3 (avant les modes), car c'est la demande
> centrale « coller une IA » et il valide le découplage du cœur tôt.

---

## 10. Critères d'acceptance v1 (GO / NO-GO)

- AC-01 : environnement opérationnel < 5 min sur machine Docker vierge (O1).
- AC-02 : cycle CAN complet (sniff → décodage → rejeu → injection) sans quitter CARBON.
- AC-03 : dialogue UDS complet (scan → session → DTC → seed-key documenté).
- AC-04 : mode Guidé déroule les étapes 1 à 6 avec interprétation des résultats.
- AC-05 : mode Libre affiche la position et journalise les actions.
- AC-06 : image démarre sur x86 et ARM depuis la même source.
- AC-07 : tout fonctionne sur `vcan0` sans aucun matériel.
- AC-08 : rapport de session généré en fin de parcours.
- **AC-09 (nouveau)** : une même session est pilotable par un **modèle local** et par un **modèle
  frontière** via MCP, sans modification du code CARBON (O6).
- **AC-10 (nouveau)** : aucune action destructrice (injection, clear DTC, écriture UDS) n'est
  exécutée — même demandée par l'IA — sans confirmation explicite.
- **AC-11 (nouveau)** : TUI et Web exposent le même jeu d'actions sur le même cœur (O7).
- **AC-12 (nouveau)** : un **mode d'emploi** permet à un nouvel opérateur d'installer et de boucler
  un parcours CAN/UDS sur `vcan0` sans aide extérieure.
- **AC-13 (nouveau)** : le **matériel réel est exploitable** — un adaptateur OBD-II/CAN USB en
  passthrough crée/attache `can0` et capture du trafic ; une antenne Wi-Fi USB passe en mode
  monitor et un dongle BLE est découvert, depuis le conteneur, sans `--privileged` global.

---

## 11. Ce qui reste au constructeur

- Choix fin des bibliothèques (ex : `udsoncan` vs `python-uds`), structure des paquets Python,
  gestionnaire d'environnement (poetry/uv), outil de test.
- Format exact du fichier YAML de méthodologie (schéma versionné) et du format de rapport
  (Markdown/HTML, EF-51 ; hook PwnDoc en v2, EF-52).
- Détail des adaptateurs d'outils et du mécanisme déclaratif d'ajout (ENF-30).
- Choix du framework front Web et direction visuelle (via `frontend-design`).
- Stratégie de tests à la construction d'image (ENF-31) et CI multi-arch.
- Mécanisme de génération/stockage du token MCP.

---

## 12. Questions à trancher avec l'auteur

- [x] Licence : **GPLv3** (validé) — audit des licences amont à réaliser avant le 1er publish public.
- [x] Air-gap : **config supportée** (validé), pas une exigence dure v1.
- [x] Accès CAN : **`python-can`** (validé).
- [ ] Nom de code définitif (CARBON provisoire) — non bloquant.

> **Statut : doc approuvé par l'auteur le 2026-11-19.** Socle v0.1 livré et mergé (PR #1).
> **Périmètre v0.2 (UDS, Option A) approuvé le 2026-11-20** (§5.6.1) ; Option C planifiée comme
> jalon d'apprentissage ultérieur. v0.2 livré (PR #2).
> **Périmètre v0.3 (MCP + IA branchable) approuvé le 2026-11-22** (§5.4.1) : 10 adaptateurs en
> outils MCP, garde-fou destructif à file `pending-approval` approuvée hors pipe MCP, O6 prouvé par
> client MCP en mémoire. v0.3 livré (PR #4, base `main` propre).
> **Périmètre v0.4 (Mode Guidé) approuvé le 2026-11-22** (§5.2.1) : moteur de méthodologie YAML
> (étapes 1→6 sur ECU simulée), langage de conditions fermé sur `ToolResult`, état persistant +
> reprise, modes **Guidé/Libre + bascule** (la logique des deux modes et la bascule EF-24 arrivent
> en v0.4 côté moteur/TUI ; le **Web** et la **carte visuelle** de surface d'attaque restent en v0.5),
> TUI Textual complète. Étape suivante : plan d'implémentation v0.4.
