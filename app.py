from flask import Flask, render_template, request, redirect, jsonify
from datetime import datetime
import database

from dotenv import load_dotenv
load_dotenv()

import anthropic
import base64
import json
import unicodedata

client_anthropic = anthropic.Anthropic()  # lit automatiquement ANTHROPIC_API_KEY

# S'assure que la base est prête au démarrage (utile en production,
# où le fichier cave.db peut ne pas encore exister)
database.init_db()
database.peupler_cepages()

app = Flask(__name__)

@app.route("/")
def accueil():
    recherche = request.args.get("recherche", "").strip()
    bouteilles = database.get_toutes_bouteilles(recherche=recherche or None)
    a_boire_bientot = database.get_bouteilles_a_boire_bientot()
    stats = database.get_statistiques()
    return render_template("liste.html", bouteilles=bouteilles,
                            a_boire_bientot=a_boire_bientot[:3],
                            nb_a_boire_bientot=len(a_boire_bientot),
                            stats=stats, recherche=recherche)


@app.route("/historique")
def historique():
    bouteilles = database.get_historique()
    return render_template("historique.html", bouteilles=bouteilles)

@app.route("/a-boire-bientot")
def a_boire_bientot_complet():
    bouteilles = database.get_bouteilles_a_boire_bientot()
    return render_template("a_boire_bientot.html", bouteilles=bouteilles)

@app.route("/bouteilles/ajouter", methods=["GET", "POST"])
def ajouter():
    if request.method == "POST":
        cepage_ids = [int(cid) for cid in request.form.getlist("cepages")]
        database.ajouter_bouteille(
            nom=request.form["nom"],
            domaine=request.form["domaine"] or None,
            appellation=request.form["appellation"] or None,
            couleur=request.form["couleur"],
            millesime=request.form["millesime"] or None,
            quantite=int(request.form["quantite"]),
            prix=request.form["prix"] or None,
            emplacement=request.form["emplacement"] or None,
            note=request.form["note"] or None,
            annee_debut=request.form["annee_debut"] or None,
            annee_fin=request.form["annee_fin"] or None,
            cepage_ids=cepage_ids,
        )
        return redirect("/")

    cepages = database.get_tous_cepages_avec_couleurs()
    annee_defaut = datetime.now().year - 1
    return render_template("formulaire.html", bouteille=None, cepages=cepages,
                            cepages_selectionnes=[], annee_defaut=annee_defaut)


@app.route("/bouteilles/<int:id_bouteille>")
def detail(id_bouteille):
    bouteille = database.get_bouteille_par_id(id_bouteille)
    cepages = database.get_cepages_bouteille(id_bouteille)
    return render_template("detail.html", bouteille=bouteille, cepages=cepages)


@app.route("/bouteilles/<int:id_bouteille>/modifier", methods=["GET", "POST"])
def modifier(id_bouteille):
    if request.method == "POST":
        cepage_ids = [int(cid) for cid in request.form.getlist("cepages")]
        database.modifier_bouteille(
            id_bouteille,
            nom=request.form["nom"],
            domaine=request.form["domaine"] or None,
            appellation=request.form["appellation"] or None,
            couleur=request.form["couleur"],
            millesime=request.form["millesime"] or None,
            quantite=int(request.form["quantite"]),
            prix=request.form["prix"] or None,
            emplacement=request.form["emplacement"] or None,
            note=request.form["note"] or None,
            annee_debut=request.form["annee_debut"] or None,
            annee_fin=request.form["annee_fin"] or None,
            cepage_ids=cepage_ids,
        )
        return redirect(f"/bouteilles/{id_bouteille}")

    bouteille = database.get_bouteille_par_id(id_bouteille)
    cepages = database.get_tous_cepages_avec_couleurs()
    cepages_selectionnes = [c["id"] for c in database.get_cepages_bouteille(id_bouteille)]
    return render_template("formulaire.html", bouteille=bouteille, cepages=cepages,
                            cepages_selectionnes=cepages_selectionnes, annee_defaut=None)


@app.route("/bouteilles/<int:id_bouteille>/supprimer", methods=["POST"])
def supprimer(id_bouteille):
    database.supprimer_bouteille(id_bouteille)
    return redirect("/")


@app.route("/bouteilles/<int:id_bouteille>/retirer", methods=["POST"])
def retirer(id_bouteille):
    database.retirer_une_bouteille(id_bouteille)
    return redirect("/")

@app.route("/bouteilles/<int:id_bouteille>/noter", methods=["POST"])
def noter(id_bouteille):
    donnees = request.get_json(silent=True) or {}

    try:
        note = int(donnees.get("note"))
    except (TypeError, ValueError):
        return jsonify({"succes": False, "erreur": "Note invalide"}), 400

    if note < 0 or note > 5:
        return jsonify({"succes": False, "erreur": "La note doit être entre 0 et 5"}), 400

    database.noter_bouteille(id_bouteille, note)
    return jsonify({"succes": True, "note": note})

def normaliser(texte):
    """Enlève les accents et met en minuscule pour comparer deux noms sans se soucier des accents/majuscules."""
    if not texte:
        return ""
    texte = unicodedata.normalize('NFD', texte)
    texte = ''.join(c for c in texte if unicodedata.category(c) != 'Mn')
    return texte.lower().strip()


def nettoyer_json(texte):
    """Retire d'éventuelles balises markdown ```json autour de la réponse."""
    texte = texte.strip()
    if texte.startswith("```"):
        texte = texte.split("\n", 1)[1] if "\n" in texte else texte
        texte = texte.rsplit("```", 1)[0].strip()
    return texte


@app.route("/scan-etiquette", methods=["POST"])
def scan_etiquette():
    fichier = request.files.get("photo")
    if not fichier:
        return jsonify({"erreur": "Aucune image reçue"}), 400

    image_base64 = base64.standard_b64encode(fichier.read()).decode("utf-8")
    media_type = fichier.mimetype or "image/jpeg"

    prompt = """Tu es un assistant qui lit les étiquettes de vin. Analyse l'image et renvoie UNIQUEMENT un objet JSON valide (rien avant, rien après, pas de balises markdown), avec exactement ces clés :

{
  "nom": string ou null,
  "domaine": string ou null,
  "appellation": string ou null,
  "couleur": une valeur parmi "Rouge", "Blanc", "Rosé", "Effervescent", ou null,
  "millesime": nombre (année à 4 chiffres) ou null,
  "cepages": liste de noms de cépages en français repérés sur l'étiquette (liste vide si aucun)
}

Si une information n'est pas lisible ou absente, mets null (ou liste vide pour cepages). Ne devine pas au-delà de ce qui est visible sur l'étiquette."""

    try:
        message = client_anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_base64},
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        donnees = json.loads(nettoyer_json(message.content[0].text))
    except Exception as e:
        return jsonify({"erreur": f"Échec de l'analyse de l'étiquette : {e}"}), 500

    # Faire correspondre les noms de cépages renvoyés par Claude aux cépages existants en base
    tous_cepages = database.get_tous_cepages_avec_couleurs()
    cepage_ids = []
    for nom_cepage in donnees.get("cepages") or []:
        for c in tous_cepages:
            if normaliser(c['nom']) == normaliser(nom_cepage):
                cepage_ids.append(c['id'])
                break

    donnees["cepage_ids"] = cepage_ids
    return jsonify(donnees)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)