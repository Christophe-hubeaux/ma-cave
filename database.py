import os
from urllib.parse import urlparse
import ssl
import pg8000.dbapi
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# En local comme en production, on se connecte à la même base PostgreSQL
# (Render fournit une "External Database URL" utilisable depuis ta machine).
DATABASE_URL = os.environ.get("DATABASE_URL")

if isinstance(DATABASE_URL, bytes):
    DATABASE_URL = DATABASE_URL.decode("utf-8")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL n'est pas définie. Vérifie que ton fichier .env contient bien "
        "une ligne DATABASE_URL=... et qu'il se trouve à la racine du projet."
    )


def get_connection():
    url = urlparse(DATABASE_URL)
    contexte_ssl = ssl.create_default_context()
    conn = pg8000.dbapi.connect(
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port or 5432,
        database=url.path.lstrip("/"),
        ssl_context=contexte_ssl,
    )
    return conn


def _en_dict(cursor, ligne):
    """pg8000 renvoie les lignes comme des tuples ; on les convertit en dict
    pour garder le même style d'accès (ligne["colonne"]) que le reste du code."""
    if ligne is None:
        return None
    colonnes = [desc[0] for desc in cursor.description]
    return dict(zip(colonnes, ligne))


def _fetchone(cursor):
    return _en_dict(cursor, cursor.fetchone())


def _fetchall(cursor):
    colonnes = [desc[0] for desc in cursor.description]
    return [dict(zip(colonnes, ligne)) for ligne in cursor.fetchall()]


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # La table des comptes doit exister avant qu'on y fasse référence depuis "bouteilles"
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            nom TEXT NOT NULL UNIQUE,
            pin_hash TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bouteilles (
            id SERIAL PRIMARY KEY,
            nom TEXT NOT NULL,
            domaine TEXT,
            appellation TEXT,
            couleur TEXT NOT NULL,
            millesime INTEGER,
            quantite INTEGER NOT NULL DEFAULT 1,
            prix REAL,
            emplacement TEXT,
            note TEXT,
            annee_a_boire_debut INTEGER,
            annee_a_boire_fin INTEGER,
            statut TEXT NOT NULL DEFAULT 'active',
            note_etoiles INTEGER NOT NULL DEFAULT 0
        )
    """)

    # PostgreSQL gère nativement le "ajoute la colonne si elle n'existe pas",
    # donc plus besoin du try/except qu'il fallait faire avec SQLite.
    cursor.execute("ALTER TABLE bouteilles ADD COLUMN IF NOT EXISTS statut TEXT NOT NULL DEFAULT 'active'")
    cursor.execute("ALTER TABLE bouteilles ADD COLUMN IF NOT EXISTS note_etoiles INTEGER NOT NULL DEFAULT 0")
    # Chaque bouteille appartient à un compte. Nullable pour l'instant : les bouteilles
    # créées avant l'ajout des comptes seront rattachées à Christophe par creer_utilisateurs().
    cursor.execute("ALTER TABLE bouteilles ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cepages (
            id SERIAL PRIMARY KEY,
            nom TEXT NOT NULL UNIQUE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cepage_couleurs (
            cepage_id INTEGER NOT NULL,
            couleur TEXT NOT NULL,
            PRIMARY KEY (cepage_id, couleur),
            FOREIGN KEY (cepage_id) REFERENCES cepages(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bouteille_cepages (
            bouteille_id INTEGER NOT NULL,
            cepage_id INTEGER NOT NULL,
            PRIMARY KEY (bouteille_id, cepage_id),
            FOREIGN KEY (bouteille_id) REFERENCES bouteilles(id) ON DELETE CASCADE,
            FOREIGN KEY (cepage_id) REFERENCES cepages(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


def creer_utilisateurs():
    """Crée les comptes Christophe et Pierre s'ils n'existent pas encore, à partir
    des PIN définis en variables d'environnement (PIN_CHRISTOPHE, PIN_PIERRE).
    Rattache aussi à Christophe les bouteilles déjà en base avant l'ajout des comptes."""
    conn = get_connection()
    cursor = conn.cursor()

    comptes = [
        ("Christophe", os.environ.get("PIN_CHRISTOPHE")),
        ("Pierre", os.environ.get("PIN_PIERRE")),
    ]

    for nom, pin in comptes:
        if not pin:
            continue  # variable pas encore définie : on ne crée pas le compte pour l'instant
        cursor.execute("SELECT id FROM users WHERE nom = %s", (nom,))
        if _fetchone(cursor) is None:
            cursor.execute(
                "INSERT INTO users (nom, pin_hash) VALUES (%s, %s)",
                (nom, generate_password_hash(pin))
            )
    conn.commit()

    cursor.execute("SELECT id FROM users WHERE nom = %s", ("Christophe",))
    christophe = _fetchone(cursor)
    if christophe:
        cursor.execute(
            "UPDATE bouteilles SET user_id = %s WHERE user_id IS NULL",
            (christophe["id"],)
        )
        conn.commit()

    conn.close()


def get_utilisateurs():
    """Liste des comptes existants, pour l'écran de connexion."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nom FROM users ORDER BY id")
    utilisateurs = _fetchall(cursor)
    conn.close()
    return utilisateurs


def verifier_pin(nom, pin):
    """Vérifie le PIN d'un compte. Retourne son id si correct, None sinon."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, pin_hash FROM users WHERE nom = %s", (nom,))
    utilisateur = _fetchone(cursor)
    conn.close()
    if utilisateur and check_password_hash(utilisateur["pin_hash"], pin):
        return utilisateur["id"]
    return None


def peupler_cepages():
    """Remplit la liste des cépages courants avec leurs couleurs associées, si la table est vide."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as nb FROM cepages")
    if _fetchone(cursor)["nb"] == 0:
        cepages_courants = {
            "Cabernet Sauvignon": ["Rouge", "Rosé"],
            "Merlot": ["Rouge", "Rosé"],
            "Cabernet Franc": ["Rouge", "Rosé"],
            "Pinot Noir": ["Rouge", "Rosé", "Effervescent"],
            "Syrah": ["Rouge", "Rosé"],
            "Grenache": ["Rouge", "Rosé"],
            "Mourvèdre": ["Rouge", "Rosé"],
            "Malbec": ["Rouge"],
            "Gamay": ["Rouge", "Rosé"],
            "Carignan": ["Rouge", "Rosé"],
            "Chardonnay": ["Blanc", "Effervescent"],
            "Sauvignon Blanc": ["Blanc"],
            "Chenin Blanc": ["Blanc", "Effervescent"],
            "Riesling": ["Blanc"],
            "Viognier": ["Blanc"],
            "Marsanne": ["Blanc"],
            "Roussanne": ["Blanc"],
            "Sémillon": ["Blanc"],
            "Pinot Gris": ["Blanc", "Rosé"],
            "Gewurztraminer": ["Blanc"],
            "Muscat": ["Blanc", "Effervescent"],
        }
        for nom, couleurs in cepages_courants.items():
            cursor.execute("INSERT INTO cepages (nom) VALUES (%s) RETURNING id", (nom,))
            cepage_id = _fetchone(cursor)["id"]
            for couleur in couleurs:
                cursor.execute(
                    "INSERT INTO cepage_couleurs (cepage_id, couleur) VALUES (%s, %s)",
                    (cepage_id, couleur)
                )
        conn.commit()
    conn.close()


def get_tous_cepages_avec_couleurs():
    """Retourne tous les cépages avec la liste des couleurs auxquelles ils sont associés (partagé entre comptes)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cepages ORDER BY nom")
    cepages = _fetchall(cursor)

    resultat = []
    for c in cepages:
        cursor.execute("SELECT couleur FROM cepage_couleurs WHERE cepage_id = %s", (c["id"],))
        couleurs = [row["couleur"] for row in _fetchall(cursor)]
        resultat.append({"id": c["id"], "nom": c["nom"], "couleurs": couleurs})

    conn.close()
    return resultat


def get_cepages_bouteille(bouteille_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.nom FROM cepages c
        JOIN bouteille_cepages bc ON bc.cepage_id = c.id
        WHERE bc.bouteille_id = %s
        ORDER BY c.nom
    """, (bouteille_id,))
    cepages = _fetchall(cursor)
    conn.close()
    return cepages


def lier_cepages_bouteille(bouteille_id, cepage_ids):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bouteille_cepages WHERE bouteille_id = %s", (bouteille_id,))
    for cid in cepage_ids:
        cursor.execute(
            "INSERT INTO bouteille_cepages (bouteille_id, cepage_id) VALUES (%s, %s)",
            (bouteille_id, cid)
        )
    conn.commit()
    conn.close()


def ajouter_bouteille(user_id, nom, domaine, appellation, couleur, millesime, quantite, prix,
                       emplacement, note, annee_debut, annee_fin, cepage_ids=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bouteilles (user_id, nom, domaine, appellation, couleur, millesime, quantite, prix, emplacement, note, annee_a_boire_debut, annee_a_boire_fin)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (user_id, nom, domaine, appellation, couleur, millesime, quantite, prix, emplacement, note, annee_debut, annee_fin))
    nouvel_id = _fetchone(cursor)["id"]
    conn.commit()
    conn.close()

    if cepage_ids:
        lier_cepages_bouteille(nouvel_id, cepage_ids)

    return nouvel_id


def get_toutes_bouteilles(user_id, recherche=None):
    """Ne retourne que les bouteilles actives de cet utilisateur. Si 'recherche' est fourni, filtre sur nom ou domaine."""
    conn = get_connection()
    cursor = conn.cursor()

    if recherche:
        motif = f"%{recherche}%"
        cursor.execute("""
            SELECT * FROM bouteilles
            WHERE statut = 'active' AND user_id = %s
            AND (nom ILIKE %s OR domaine ILIKE %s)
            ORDER BY nom
        """, (user_id, motif, motif))
    else:
        cursor.execute("SELECT * FROM bouteilles WHERE statut = 'active' AND user_id = %s ORDER BY nom", (user_id,))

    bouteilles = _fetchall(cursor)
    conn.close()
    return bouteilles


def get_historique(user_id):
    """Retourne les bouteilles terminées (bues en totalité) de cet utilisateur."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bouteilles WHERE statut = 'terminee' AND user_id = %s ORDER BY nom", (user_id,))
    bouteilles = _fetchall(cursor)
    conn.close()
    return bouteilles


def get_bouteille_par_id(id_bouteille, user_id):
    """Ne renvoie la bouteille que si elle appartient à cet utilisateur (sinon None)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bouteilles WHERE id = %s AND user_id = %s", (id_bouteille, user_id))
    bouteille = _fetchone(cursor)
    conn.close()
    return bouteille


def modifier_bouteille(id_bouteille, user_id, nom, domaine, appellation, couleur, millesime, quantite,
                        prix, emplacement, note, annee_debut, annee_fin, cepage_ids=None):
    statut = "terminee" if int(quantite) <= 0 else "active"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE bouteilles
        SET nom = %s, domaine = %s, appellation = %s, couleur = %s, millesime = %s,
            quantite = %s, prix = %s, emplacement = %s, note = %s,
            annee_a_boire_debut = %s, annee_a_boire_fin = %s, statut = %s
        WHERE id = %s AND user_id = %s
    """, (nom, domaine, appellation, couleur, millesime, quantite, prix, emplacement, note,
          annee_debut, annee_fin, statut, id_bouteille, user_id))
    conn.commit()
    conn.close()

    lier_cepages_bouteille(id_bouteille, cepage_ids or [])


def supprimer_bouteille(id_bouteille, user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bouteilles WHERE id = %s AND user_id = %s", (id_bouteille, user_id))
    conn.commit()
    conn.close()


def retirer_une_bouteille(id_bouteille, user_id):
    """Diminue la quantité de 1. Passe la bouteille en statut 'terminee' quand elle atteint 0 (au lieu de la supprimer)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT quantite FROM bouteilles WHERE id = %s AND user_id = %s", (id_bouteille, user_id))
    resultat = _fetchone(cursor)

    if resultat and resultat["quantite"] > 1:
        cursor.execute("UPDATE bouteilles SET quantite = quantite - 1 WHERE id = %s AND user_id = %s", (id_bouteille, user_id))
    elif resultat:
        cursor.execute("UPDATE bouteilles SET quantite = 0, statut = 'terminee' WHERE id = %s AND user_id = %s", (id_bouteille, user_id))

    conn.commit()
    conn.close()


def noter_bouteille(id_bouteille, user_id, note_etoiles):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bouteilles SET note_etoiles = %s WHERE id = %s AND user_id = %s", (note_etoiles, id_bouteille, user_id))
    conn.commit()
    conn.close()


def get_bouteilles_a_boire_bientot(user_id):
    annee_actuelle = datetime.now().year
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM bouteilles
        WHERE statut = 'active' AND user_id = %s
        AND annee_a_boire_fin IS NOT NULL
        AND annee_a_boire_fin <= %s
        ORDER BY annee_a_boire_fin ASC
    """, (user_id, annee_actuelle + 1))
    bouteilles = _fetchall(cursor)
    conn.close()
    return bouteilles


def get_statistiques(user_id):
    """Calcule les statistiques globales de la cave de cet utilisateur (bouteilles actives uniquement)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as nb FROM bouteilles WHERE statut = 'active' AND user_id = %s", (user_id,))
    nb_references = _fetchone(cursor)["nb"]

    cursor.execute("SELECT COALESCE(SUM(quantite), 0) as total FROM bouteilles WHERE statut = 'active' AND user_id = %s", (user_id,))
    nb_bouteilles = _fetchone(cursor)["total"]

    cursor.execute("""
        SELECT COALESCE(SUM(prix * quantite), 0) as total
        FROM bouteilles WHERE statut = 'active' AND user_id = %s AND prix IS NOT NULL
    """, (user_id,))
    valeur_totale = _fetchone(cursor)["total"]

    cursor.execute("""
        SELECT couleur, COALESCE(SUM(quantite), 0) as total
        FROM bouteilles WHERE statut = 'active' AND user_id = %s
        GROUP BY couleur
    """, (user_id,))
    repartition_couleurs = {row["couleur"]: row["total"] for row in _fetchall(cursor)}

    conn.close()
    return {
        "nb_references": nb_references,
        "nb_bouteilles": nb_bouteilles,
        "valeur_totale": valeur_totale,
        "repartition_couleurs": repartition_couleurs,
    }


if __name__ == "__main__":
    init_db()
    peupler_cepages()
    creer_utilisateurs()
    print("Base de données initialisée avec succès !")