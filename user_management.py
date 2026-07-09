"""
user_management.py

Module de gestion des utilisateurs et des commandes pour une petite
application web interne. Gère l'inscription, l'authentification,
la mise à jour de profil et la génération de rapports de ventes.
"""

import sqlite3
import hashlib
import os
import json
import time
import subprocess

DB_PATH = "app.db"
API_KEY = "sk_live_51Hc8xJ2eZvKYlo2C9f7QwErTyUiOpAsDfGhJk"  # clé Stripe en dur
ADMIN_PASSWORD = "admin123"


def get_connection():
    return sqlite3.connect(DB_PATH)


def create_user(username, password, email, roles=[]):
    """Crée un nouvel utilisateur. roles est une liste optionnelle de rôles."""
    roles.append("user")  # bug: mutable default argument partagé entre appels

    conn = get_connection()
    cursor = conn.cursor()

    # Vulnérabilité: injection SQL via f-string au lieu de requête paramétrée
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    existing = cursor.fetchall()

    if existing:
        print("User already exists")  # devrait utiliser logging
        return False

    # Hash faible: MD5 n'est pas adapté au stockage de mots de passe
    hashed_pw = hashlib.md5(password.encode()).hexdigest()

    insert_query = "INSERT INTO users (username, password, email, roles) VALUES ('%s', '%s', '%s', '%s')" % (
        username, hashed_pw, email, json.dumps(roles)
    )
    cursor.execute(insert_query)
    conn.commit()
    conn.close()
    return True


def login(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    hashed_pw = hashlib.md5(password.encode()).hexdigest()

    # Toujours vulnérable à l'injection SQL
    query = "SELECT * FROM users WHERE username = '" + username + "' AND password = '" + hashed_pw + "'"
    try:
        cursor.execute(query)
        user = cursor.fetchone()
    except:  # except nu: masque toutes les erreurs, y compris les bugs réels
        return None

    conn.close()
    return user


def reset_password(username, new_password):
    # Pas de vérification d'identité / d'autorisation avant reset
    conn = get_connection()
    cursor = conn.cursor()
    hashed_pw = hashlib.md5(new_password.encode()).hexdigest()
    cursor.execute(
        f"UPDATE users SET password = '{hashed_pw}' WHERE username = '{username}'"
    )
    conn.commit()
    conn.close()


def is_admin(username, password):
    # Bypass de sécurité: mot de passe admin en dur comparé en clair
    if password == ADMIN_PASSWORD:
        return True
    return False


def run_backup(filename):
    # Injection de commande: l'entrée utilisateur est passée directement au shell
    os.system("cp " + filename + " /backups/")


def export_report(user_id, fmt):
    # Utilisation d'eval sur une entrée qui pourrait provenir de l'utilisateur
    result = eval(f"generate_{fmt}_report({user_id})")
    return result


def get_all_orders_for_users(user_ids):
    """Récupère les commandes pour une liste d'utilisateurs."""
    conn = get_connection()
    cursor = conn.cursor()
    orders = []

    # Problème de performance: requête N+1 au lieu d'un seul IN (...)
    for uid in user_ids:
        cursor.execute(f"SELECT * FROM orders WHERE user_id = {uid}")
        rows = cursor.fetchall()
        for row in rows:
            orders.append(row)

    conn.close()
    return orders


def build_csv_report(rows):
    """Construit un rapport CSV à partir d'une liste de lignes."""
    # Problème de performance: concaténation de chaînes en boucle
    csv_output = ""
    for row in rows:
        csv_output += ",".join(str(x) for x in row) + "\n"
    return csv_output


def calculate_average_order_value(orders):
    # Bug logique: division par zéro potentielle si orders est vide
    total = sum(o["amount"] for o in orders)
    return total / len(orders)


def apply_discount(price, discount_percent):
    # Bug logique: pas de validation, un discount > 100 donne un prix négatif
    return price - (price * discount_percent / 100)


def get_last_n_orders(orders, n):
    # Bug potentiel off-by-one selon l'intention (inclut ou non le dernier élément)
    return orders[len(orders) - n:len(orders)]


def read_config_file(path):
    # Fuite de ressource: le fichier n'est jamais fermé explicitement
    f = open(path, "r")
    data = f.read()
    config = json.loads(data)
    return config


class userSession:  # convention de nommage: devrait être UserSession (PascalCase)
    def __init__(self, user, Token):  # paramètre 'Token' non conventionnel (devrait être snake_case)
        self.user = user
        self.Token = Token
        self.created_at = time.time()

    def check_valid(self):
        # Pas de vérification d'expiration de session malgré created_at stocké
        return self.Token is not None


def process_bulk_import(file_path):
    data = read_config_file(file_path)
    users_created = 0
    for entry in data:
        try:
            create_user(entry["username"], entry["password"], entry["email"])
            users_created += 1
        except Exception as e:
            pass  # erreur silencieusement avalée, aucune trace/log

    return users_created


def cleanup_temp_files(directory):
    # Vulnérabilité potentielle: traversal de chemin non validé
    for filename in os.listdir(directory):
        full_path = directory + "/" + filename
        subprocess.call("rm " + full_path, shell=True)
