import sqlite3
from datetime import datetime

def get_connection():
    conn = sqlite3.connect("cave.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bouteilles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # Filet de sécurité si la table existait déjà sans la colonne "statut"
    try:
        cursor.execute("ALTER TABLE bouteilles ADD COLUMN statut TEXT NOT NULL DEFAULT 'active'")
    except sqlite3.OperationalError:
        pass

    # Filet de sécurité si la table existait déjà sans la colonne "note_etoiles"
    try:
        cursor.execute("ALTER TABLE bouteilles ADD COLUMN note_etoiles INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cepages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL UNIQUE
        )
    """)

    # Quelles couleurs de vin utilisent ce cépage (un cépage peut concerner plusieurs couleurs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cepage_couleurs (
            cepage_id INTEGER NOT NULL,
            couleur TEXT NOT NULL,
            PRIMARY KEY (cepage_id, couleur),
            FOREIGN KEY (cepage_id) REFERENCES cepages(id) ON DELETE CASCADE
        )
    """)

    # Liaison bouteille <-> cépages (plusieurs-à-plusieurs)
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


def peupler_cepages():
    """Remplit la liste des cépages courants avec leurs couleurs associées, si la table est vide."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM cepages")
    if cursor.fetchone()[0] == 0:
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
            cursor.execute("INSERT INTO cepages (nom) VALUES (?)", (nom,))
            cepage_id = cursor.lastrowid
            for couleur in couleurs:
                cursor.execute(
                    "INSERT INTO cepage_couleurs (cepage_id, couleur) VALUES (?, ?)",
                    (cepage_id, couleur)
                )
        conn.commit()
    conn.close()


def get_tous_cepages_avec_couleurs():
    """Retourne tous les cépages avec la liste des couleurs auxquelles ils sont associés."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cepages ORDER BY nom")
    cepages = cursor.fetchall()

    resultat = []
    for c in cepages:
        cursor.execute("SELECT couleur FROM cepage_couleurs WHERE cepage_id = ?", (c["id"],))
        couleurs = [row["couleur"] for row in cursor.fetchall()]
        resultat.append({"id": c["id"], "nom": c["nom"], "couleurs": couleurs})

    conn.close()
    return resultat


def get_cepages_bouteille(bouteille_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.nom FROM cepages c
        JOIN bouteille_cepages bc ON bc.cepage_id = c.id
        WHERE bc.bouteille_id = ?
        ORDER BY c.nom
    """, (bouteille_id,))
    cepages = cursor.fetchall()
    conn.close()
    return cepages


def lier_cepages_bouteille(bouteille_id, cepage_ids):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bouteille_cepages WHERE bouteille_id = ?", (bouteille_id,))
    for cid in cepage_ids:
        cursor.execute(
            "INSERT INTO bouteille_cepages (bouteille_id, cepage_id) VALUES (?, ?)",
            (bouteille_id, cid)
        )
    conn.commit()
    conn.close()


def ajouter_bouteille(nom, domaine, appellation, couleur, millesime, quantite, prix,
                       emplacement, note, annee_debut, annee_fin, cepage_ids=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bouteilles (nom, domaine, appellation, couleur, millesime, quantite, prix, emplacement, note, annee_a_boire_debut, annee_a_boire_fin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (nom, domaine, appellation, couleur, millesime, quantite, prix, emplacement, note, annee_debut, annee_fin))
    nouvel_id = cursor.lastrowid
    conn.commit()
    conn.close()

    if cepage_ids:
        lier_cepages_bouteille(nouvel_id, cepage_ids)

    return nouvel_id


def get_toutes_bouteilles(recherche=None):
    """Ne retourne que les bouteilles actives. Si 'recherche' est fourni, filtre sur nom ou domaine."""
    conn = get_connection()
    cursor = conn.cursor()

    if recherche:
        motif = f"%{recherche}%"
        cursor.execute("""
            SELECT * FROM bouteilles
            WHERE statut = 'active'
            AND (nom LIKE ? OR domaine LIKE ?)
            ORDER BY nom
        """, (motif, motif))
    else:
        cursor.execute("SELECT * FROM bouteilles WHERE statut = 'active' ORDER BY nom")

    bouteilles = cursor.fetchall()
    conn.close()
    return bouteilles


def get_historique():
    """Retourne les bouteilles terminées (bues en totalité)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bouteilles WHERE statut = 'terminee' ORDER BY nom")
    bouteilles = cursor.fetchall()
    conn.close()
    return bouteilles


def get_bouteille_par_id(id_bouteille):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bouteilles WHERE id = ?", (id_bouteille,))
    bouteille = cursor.fetchone()
    conn.close()
    return bouteille


def modifier_bouteille(id_bouteille, nom, domaine, appellation, couleur, millesime, quantite,
                        prix, emplacement, note, annee_debut, annee_fin, cepage_ids=None):
    statut = "terminee" if int(quantite) <= 0 else "active"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE bouteilles
        SET nom = ?, domaine = ?, appellation = ?, couleur = ?, millesime = ?,
            quantite = ?, prix = ?, emplacement = ?, note = ?,
            annee_a_boire_debut = ?, annee_a_boire_fin = ?, statut = ?
        WHERE id = ?
    """, (nom, domaine, appellation, couleur, millesime, quantite, prix, emplacement, note,
          annee_debut, annee_fin, statut, id_bouteille))
    conn.commit()
    conn.close()

    lier_cepages_bouteille(id_bouteille, cepage_ids or [])


def supprimer_bouteille(id_bouteille):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bouteilles WHERE id = ?", (id_bouteille,))
    conn.commit()
    conn.close()


def retirer_une_bouteille(id_bouteille):
    """Diminue la quantité de 1. Passe la bouteille en statut 'terminee' quand elle atteint 0 (au lieu de la supprimer)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT quantite FROM bouteilles WHERE id = ?", (id_bouteille,))
    resultat = cursor.fetchone()

    if resultat and resultat["quantite"] > 1:
        cursor.execute("UPDATE bouteilles SET quantite = quantite - 1 WHERE id = ?", (id_bouteille,))
    elif resultat:
        cursor.execute("UPDATE bouteilles SET quantite = 0, statut = 'terminee' WHERE id = ?", (id_bouteille,))

    conn.commit()
    conn.close()

def noter_bouteille(id_bouteille, note_etoiles):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE bouteilles SET note_etoiles = ? WHERE id = ?", (note_etoiles, id_bouteille))
    conn.commit()
    conn.close()


def get_bouteilles_a_boire_bientot():
    annee_actuelle = datetime.now().year
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM bouteilles
        WHERE statut = 'active'
        AND annee_a_boire_fin IS NOT NULL
        AND annee_a_boire_fin <= ?
        ORDER BY annee_a_boire_fin ASC
    """, (annee_actuelle + 1,))
    bouteilles = cursor.fetchall()
    conn.close()
    return bouteilles

def get_statistiques():
    """Calcule les statistiques globales de la cave (bouteilles actives uniquement)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as nb FROM bouteilles WHERE statut = 'active'")
    nb_references = cursor.fetchone()["nb"]

    cursor.execute("SELECT COALESCE(SUM(quantite), 0) as total FROM bouteilles WHERE statut = 'active'")
    nb_bouteilles = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(SUM(prix * quantite), 0) as total
        FROM bouteilles WHERE statut = 'active' AND prix IS NOT NULL
    """)
    valeur_totale = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT couleur, COALESCE(SUM(quantite), 0) as total
        FROM bouteilles WHERE statut = 'active'
        GROUP BY couleur
    """)
    repartition_couleurs = {row["couleur"]: row["total"] for row in cursor.fetchall()}

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
    print("Base de données initialisée avec succès !")