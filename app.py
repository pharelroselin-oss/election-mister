import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg
from psycopg.rows import dict_row
from datetime import datetime

app = Flask(__name__, static_folder='static')
CORS(app)

# CONFIGURATION POUR RENDER - Utilisez ces noms de variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'dpg-d4tf1uchg0os73ct4gi0-a.oregon-postgres.render.com'),
    'database': os.getenv('DB_NAME', 'election_k6jj'),
    'user': os.getenv('DB_USER', 'election_user'),
    'password': os.getenv('DB_PASSWORD', 'uIvD4UaRMcqngNl3Re643KySUFvhnRF0'),
    'port': os.getenv('DB_PORT', '5432'),
    'sslmode': 'require'  # IMPORTANT pour Render
}

# ========== FONCTION D'INITIALISATION DE LA BASE ==========
def init_database():
    """Vérifie et crée les tables si elles n'existent pas."""
    conn = None
    try:
        print("🔄 Initialisation de la base de données...")
        conn = psycopg.connect(**DB_CONFIG, row_factory=dict_row)
        cur = conn.cursor()
        
        # 1. Créer la table candidates
        cur.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id VARCHAR(50) PRIMARY KEY,
                nom VARCHAR(100) NOT NULL,
                categorie VARCHAR(20) CHECK (categorie IN ('miss', 'mister')),
                img VARCHAR(255),
                votes INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ Table 'candidates' vérifiée/créée")
        
        # 2. Créer la table transactions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                candidate_id VARCHAR(50) NOT NULL,
                methode_paiement VARCHAR(50) NOT NULL,
                code_transaction VARCHAR(100) NOT NULL,
                code_transaction_normalized VARCHAR(100) GENERATED ALWAYS AS (UPPER(code_transaction)) STORED,
                nombre_votes INTEGER NOT NULL,
                statut VARCHAR(20) DEFAULT 'pending' CHECK (statut IN ('pending', 'validated', 'rejected')),
                montant INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                validated_at TIMESTAMP,
                FOREIGN KEY (candidate_id) REFERENCES candidates(id) ON DELETE CASCADE,
                CONSTRAINT unique_code_transaction_normalized UNIQUE (code_transaction_normalized)
            )
        """)
        print("✅ Table 'transactions' vérifiée/créée")
        
        # 3. Créer les indexes
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_code_normalized 
            ON transactions(code_transaction_normalized)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_status 
            ON transactions(statut)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_candidate 
            ON transactions(candidate_id)
        """)
        print("✅ Indexes vérifiés/créés")
        
        # 4. Vérifier si des candidats existent déjà
        cur.execute("SELECT COUNT(*) FROM candidates")
        count = cur.fetchone()['count']
        
        if count == 0:
            # Insérer les candidats par défaut
            cur.execute("""
                INSERT INTO candidates (id, nom, categorie, img) VALUES
                ('miss1', 'Fatou Diop', 'miss', 'Photo/miss1.jpg'),
                ('miss2', 'Aïcha Sow', 'miss', 'Photo/miss2.jpg'),
                ('miss3', 'Mariam Diallo', 'miss', 'Photo/miss3.jpg'),
                ('mister1', 'Mamadou Fall', 'mister', 'Photo/mister1.jpg'),
                ('mister2', 'Ibrahima Ndiaye', 'mister', 'Photo/mister2.jpg'),
                ('mister3', 'Abdoulaye Diop', 'mister', 'Photo/mister3.jpg')
            """)
            print(f"✅ {cur.rowcount} candidats insérés par défaut")
        else:
            print(f"✅ {count} candidats existent déjà")
        
        conn.commit()
        print("🎉 Initialisation de la base de données terminée avec succès !")
        
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")
        if conn:
            conn.rollback()
        # Ne pas bloquer l'application si l'init échoue
    finally:
        if conn:
            conn.close()

# ========== FONCTION PRINCIPALE DE CONNEXION ==========
def get_db():
    """Obtient une connexion à la base de données."""
    try:
        conn = psycopg.connect(**DB_CONFIG, row_factory=dict_row)
        return conn
    except Exception as e:
        print(f"Erreur de connexion à la base de données: {e}")
        raise

# ========== ROUTES API ==========
@app.route('/api/candidates', methods=['GET'])
def get_candidates():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT *, 
                   CAST(REGEXP_REPLACE(id, '[^0-9]', '', 'g') AS INTEGER) as candidate_number
            FROM candidates 
            ORDER BY categorie, candidate_number
        """)
        candidates = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(candidates)
    except Exception as e:
        print(f"Erreur dans get_candidates: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500
    
@app.route('/api/candidates/<categorie>', methods=['GET'])
def get_candidates_by_category(categorie):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT *, 
                   CAST(REGEXP_REPLACE(id, '[^0-9]', '', 'g') AS INTEGER) as candidate_number
            FROM candidates 
            WHERE categorie = %s 
            ORDER BY candidate_number
        """, (categorie,))
        candidates = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(candidates)
    except Exception as e:
        print(f"Erreur dans get_candidates_by_category: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/vote', methods=['POST'])
def submit_vote():
    data = request.json
    candidate_id = data.get('candidate_id')
    payment_method = data.get('payment_method')
    transaction_code = data.get('transaction_code')
    vote_count = data.get('vote_count', 1)
    
    if not all([candidate_id, payment_method, transaction_code]):
        return jsonify({'error': 'Données manquantes'}), 400
    
    amount = vote_count * 100
    
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Vérifier si le code de transaction existe déjà
        cur.execute("""
            SELECT id, candidate_id, statut, created_at 
            FROM transactions 
            WHERE code_transaction_normalized = UPPER(%s)
        """, (transaction_code,))
        existing_transaction = cur.fetchone()
        
        if existing_transaction:
            transaction_id, existing_candidate_id, status, created_at = existing_transaction
            return jsonify({
                'error': 'Code de transaction déjà utilisé',
                'exists': True,
                'transaction_id': transaction_id,
                'candidate_id': existing_candidate_id,
                'status': status,
                'created_at': created_at.isoformat() if created_at else None
            }), 409
        
        # Insérer la nouvelle transaction
        cur.execute("""
            INSERT INTO transactions (candidate_id, methode_paiement, code_transaction, nombre_votes, montant)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (candidate_id, payment_method, transaction_code, vote_count, amount))
        
        transaction_id = cur.fetchone()['id']
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({
            'message': 'Transaction enregistrée, en attente de validation',
            'transaction_id': transaction_id
        }), 201
        
    except Exception as e:
        print(f"Erreur dans submit_vote: {e}")
        if 'conn' in locals():
            conn.rollback()
        return jsonify({'error': f'Erreur: {str(e)}'}), 500

@app.route('/api/check-transaction/<code>', methods=['GET'])
def check_transaction_code(code):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT t.*, c.nom as candidate_name
            FROM transactions t
            LEFT JOIN candidates c ON t.candidate_id = c.id
            WHERE code_transaction_normalized = UPPER(%s)
            ORDER BY t.created_at DESC
            LIMIT 1
        """, (code,))
        
        transaction = cur.fetchone()
        cur.close()
        conn.close()
        
        if transaction:
            return jsonify({
                'exists': True,
                'transaction': transaction
            })
        else:
            return jsonify({
                'exists': False
            })
            
    except Exception as e:
        print(f"Erreur dans check_transaction_code: {e}")
        return jsonify({'error': 'Erreur de vérification'}), 500

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    password = data.get('password')
    
    if not password:
        return jsonify({'error': 'Mot de passe requis'}), 400
    
    if password == '2025':
        return jsonify({'message': 'Connexion réussie', 'token': 'admin_token'}), 200
    else:
        return jsonify({'error': 'Mot de passe incorrect'}), 401

@app.route('/api/admin/transactions/pending', methods=['GET'])
def get_pending_transactions():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT t.*, c.nom as candidate_name,
                   c.categorie as candidate_category,
                   CAST(REGEXP_REPLACE(c.id, '[^0-9]', '', 'g') AS INTEGER) as candidate_number
            FROM transactions t
            JOIN candidates c ON t.candidate_id = c.id
            WHERE t.statut = 'pending'
            ORDER BY t.created_at DESC
        """)
        transactions = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(transactions)
    except Exception as e:
        print(f"Erreur dans get_pending_transactions: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/admin/transactions/<int:transaction_id>/validate', methods=['POST'])
def validate_transaction(transaction_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT candidate_id, nombre_votes FROM transactions WHERE id = %s AND statut = 'pending'", (transaction_id,))
        result = cur.fetchone()
        
        if not result:
            return jsonify({'error': 'Transaction non trouvée'}), 404
        
        candidate_id, vote_count = result['candidate_id'], result['nombre_votes']
        
        cur.execute("UPDATE candidates SET votes = votes + %s WHERE id = %s", (vote_count, candidate_id))
        cur.execute("UPDATE transactions SET statut = 'validated', validated_at = %s WHERE id = %s", (datetime.now(), transaction_id))
        conn.commit()
        
        cur.close()
        conn.close()
        return jsonify({'message': 'Transaction validée'}), 200
    except Exception as e:
        print(f"Erreur dans validate_transaction: {e}")
        if 'conn' in locals():
            conn.rollback()
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/admin/transactions/<int:transaction_id>/reject', methods=['POST'])
def reject_transaction(transaction_id):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("UPDATE transactions SET statut = 'rejected', validated_at = %s WHERE id = %s", (datetime.now(), transaction_id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'message': 'Transaction rejetée'}), 200
    except Exception as e:
        print(f"Erreur dans reject_transaction: {e}")
        if 'conn' in locals():
            conn.rollback()
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/ranking', methods=['GET'])
def get_ranking():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT *, 
                   CAST(REGEXP_REPLACE(id, '[^0-9]', '', 'g') AS INTEGER) as candidate_number,
                   ROW_NUMBER() OVER (ORDER BY votes DESC, nom) as rank_position
            FROM candidates 
            ORDER BY votes DESC, nom
        """)
        ranking = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(ranking)
    except Exception as e:
        print(f"Erreur dans get_ranking: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM candidates")
        total_candidates = cur.fetchone()['count']
        
        cur.execute("SELECT SUM(votes) FROM candidates")
        total_votes = cur.fetchone()['sum'] or 0
        
        cur.execute("SELECT statut, COUNT(*) FROM transactions GROUP BY statut")
        transactions_stats = cur.fetchall()
        
        cur.close()
        conn.close()
        
        transactions_dict = {item['statut']: item['count'] for item in transactions_stats}
        
        return jsonify({
            'total_candidates': total_candidates,
            'total_votes': total_votes,
            'transactions': transactions_dict
        })
    except Exception as e:
        print(f"Erreur dans get_stats: {e}")
        return jsonify({'error': 'Erreur de connexion à la base de données'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        # Tenter d'initialiser la base au premier appel
        try:
            init_database()
        except:
            pass
            
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return jsonify({'status': 'healthy', 'database': 'connected'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'database': 'disconnected', 'error': str(e)}), 500

# ========== ROUTES POUR LE FRONTEND ==========
@app.route('/')
def serve_index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

# ========== DÉMARRAGE DE L'APPLICATION ==========
if __name__ == '__main__':
    # Initialiser la base au démarrage
    print("🚀 Démarrage de l'application Miss & Mister...")
    try:
        init_database()
    except Exception as e:
        print(f"⚠️ Note lors de l'initialisation: {e}")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
else:
    # Pour gunicorn (production)
    print("🚀 Application chargée par gunicorn...")
    try:
        init_database()
    except Exception as e:
        print(f"⚠️ Note: {e}")
