import os
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import psycopg
from psycopg.rows import dict_row
from psycopg import sql
from datetime import datetime
from pathlib import Path
import mimetypes

app = Flask(__name__, static_folder='static')
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://election-mister.onrender.com", "http://localhost:5000"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept"]
    }
})

# ========== CONFIGURATION AVEC URL DIRECTE ==========
DATABASE_URL = os.getenv('DATABASE_URL', 
    'postgresql://election_user:uIvD4UaRMcqngNl3Re643KySUFvhnRF0@dpg-d4tf1uchg0os73ct4gi0-a.oregon-postgres.render.com/election_k6jj'
)

# ========== FONCTION D'INITIALISATION DE LA BASE ==========
def init_database():
    """Initialise la base de données"""
    
    print("🔧 Tentative d'initialisation de la base de données...")
    
    try:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_code_normalized ON transactions(code_transaction_normalized)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(statut)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_candidate ON transactions(candidate_id)")
        print("✅ Indexes vérifiés/créés")
        
        # 4. Vérifier si des candidats existent déjà
        cur.execute("SELECT COUNT(*) FROM candidates")
        count = cur.fetchone()['count']
        
        if count == 0:
            # Insérer les candidats par défaut
            cur.execute("""
                INSERT INTO candidates (id, nom, categorie, img) VALUES
                ('miss1', 'LOVE NDAZOO', 'miss', 'miss_1.jpg'),
                ('miss2', 'KERENA KENNE', 'miss', 'miss_2.jpg'),
                ('miss3', 'DIVINE ZEKENG', 'miss', 'miss_3.jpg'),
                ('miss4', 'HILARY TCHEUNDEM', 'miss', 'miss_4.jpg'),
                ('miss5', 'ANUARITE DOUNANG', 'miss', 'miss_5.jpg'),
                ('mister1', 'ULYSSE ZELEF', 'mister', 'mass_1.jpg'),
                ('mister2', 'DOMINIQUE MBOAPFOURI', 'mister', 'mass_2.jpg'),
                ('mister3', 'ULRICH MBAKONG', 'mister', 'mass_3.jpg'),
                ('mister4', 'JORDAN BIAS', 'mister', 'mass_4.jpg'),
                ('mister5', 'OREL BEYALA', 'mister', 'mass_5.jpg'),
                ('mister6', 'WILFRIED BUGUEM', 'mister', 'mass_6.jpg'),
                ('mister7', 'PRINCELY NZO', 'mister', 'mass_7.jpg'),
                ('mister8', 'JOHANNES ELANGA', 'mister', 'mass_8.jpg')
            """)
            print(f"✅ {cur.rowcount} candidats insérés par défaut")
        else:
            print(f"✅ {count} candidats existent déjà")
        
        conn.commit()
        print("🎉 Initialisation de la base de données terminée avec succès !")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

# ========== FONCTION PRINCIPALE DE CONNEXION ==========
def get_db():
    """Obtient une connexion à la base de données."""
    try:
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
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
        success = init_database()
            
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1 as test")
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        return jsonify({
            'status': 'healthy', 
            'database': 'connected',
            'initialization_success': success,
            'test_result': result
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy', 
            'database': 'disconnected', 
            'error': str(e)
        }), 500

@app.route('/api/test', methods=['GET'])
def test_endpoint():
    return jsonify({
        'message': 'API Miss & Mister fonctionnelle',
        'timestamp': datetime.now().isoformat(),
        'service': 'Miss & Mister AHN 2025'
    }), 200

@app.route('/api/debug/files', methods=['GET'])
def debug_files():
    """Débogage complet des fichiers"""
    base_dir = Path(__file__).parent.absolute()
    static_dir = base_dir / 'static'
    photo_dir = static_dir / 'photo'
    
    result = {
        'current_dir': str(base_dir),
        'static_dir': {
            'path': str(static_dir),
            'exists': static_dir.exists(),
            'is_dir': static_dir.is_dir() if static_dir.exists() else False
        },
        'photo_dir': {
            'path': str(photo_dir),
            'exists': photo_dir.exists(),
            'is_dir': photo_dir.is_dir() if photo_dir.exists() else False,
            'files': []
        },
        'test_urls': []
    }
    
    # Liste des fichiers dans photo
    if photo_dir.exists() and photo_dir.is_dir():
        try:
            files = os.listdir(photo_dir)
            for file in files:
                file_path = photo_dir / file
                result['photo_dir']['files'].append({
                    'name': file,
                    'path': str(file_path),
                    'exists': file_path.exists(),
                    'is_file': file_path.is_file(),
                    'size': file_path.stat().st_size if file_path.exists() and file_path.is_file() else 0,
                    'extension': Path(file).suffix.lower()
                })
        except Exception as e:
            result['photo_dir']['error'] = str(e)
    
    # Générer les URLs de test
    test_images = ['miss_1.jpg', 'mass_1.jpg', 'miss_2.jpg', 'mass_2.jpg']
    for img in test_images:
        result['test_urls'].append({
            'filename': img,
            'url': f'/static/photo/{img}',
            'full_url': f'http://localhost:5000/static/photo/{img}'
        })
    
    return jsonify(result)

@app.route('/api/debug/test-image/<filename>', methods=['GET'])
def test_image(filename):
    """Tester une image spécifique"""
    photo_dir = Path(__file__).parent.absolute() / 'static' / 'photo'
    file_path = photo_dir / filename
    
    response = {
        'filename': filename,
        'requested_path': str(file_path),
        'exists': file_path.exists(),
        'is_file': file_path.is_file() if file_path.exists() else False
    }
    
    if file_path.exists() and file_path.is_file():
        try:
            response['size'] = file_path.stat().st_size
            response['content_type'] = mimetypes.guess_type(str(file_path))[0]
            
            # Essayer de lire le fichier
            with open(file_path, 'rb') as f:
                header = f.read(100)
                response['header_hex'] = header.hex()[:50]
                
                # Vérifier si c'est une image valide
                if header.startswith(b'\xff\xd8\xff'):
                    response['image_type'] = 'JPEG'
                elif header.startswith(b'\x89PNG\r\n\x1a\n'):
                    response['image_type'] = 'PNG'
                else:
                    response['image_type'] = 'Unknown'
                    
        except Exception as e:
            response['error'] = str(e)
    
    return jsonify(response)

# ========== ROUTES POUR LES IMAGES ==========
@app.route('/static/photo/<path:filename>')
def serve_image(filename):
    """Servir les images - Version robuste"""
    try:
        # Chemin absolu
        base_dir = Path(__file__).parent.absolute()
        photo_dir = base_dir / 'static' / 'photo'
        file_path = photo_dir / filename
        
        print(f"🔍 Tentative de chargement: {filename}")
        print(f"📁 Dossier photo: {photo_dir}")
        print(f"📄 Chemin complet: {file_path}")
        print(f"📄 Existe: {file_path.exists()}")
        
        if not file_path.exists():
            print(f"❌ Fichier non trouvé: {filename}")
            return jsonify({'error': f'Fichier {filename} non trouvé', 'path': str(file_path)}), 404
        
        if not file_path.is_file():
            print(f"❌ N'est pas un fichier: {filename}")
            return jsonify({'error': f'{filename} n\'est pas un fichier'}), 400
        
        # Déterminer le type MIME
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = 'application/octet-stream'
        
        print(f"✅ Fichier trouvé: {filename} ({file_path.stat().st_size} bytes, {mime_type})")
        
        # Servir le fichier avec les bons headers
        return send_file(
            str(file_path),
            mimetype=mime_type,
            as_attachment=False,
            download_name=filename
        )
        
    except Exception as e:
        print(f"❌ Erreur serveur image pour {filename}: {str(e)}")
        return jsonify({'error': str(e), 'filename': filename}), 500

# Route de secours pour les anciens chemins
@app.route('/photo/<path:filename>')
@app.route('/Photo/<path:filename>')
def serve_image_old(filename):
    """Rediriger les anciens chemins vers le nouveau"""
    print(f"🔄 Redirection ancien chemin: {filename} -> /static/photo/{filename}")
    return serve_image(filename)

# ========== ROUTES POUR LE FRONTEND ==========
@app.route('/')
def serve_index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

# ========== DÉMARRAGE DE L'APPLICATION ==========
if __name__ == '__main__':
    print("🚀 Démarrage de l'application Miss & Mister...")
    print(f"📁 Dossier courant: {Path(__file__).parent.absolute()}")
    
    # Vérifier la structure
    base_dir = Path(__file__).parent.absolute()
    static_dir = base_dir / 'static'
    photo_dir = static_dir / 'photo'
    
    print(f"📁 Static dir: {static_dir} - Existe: {static_dir.exists()}")
    print(f"📁 Photo dir: {photo_dir} - Existe: {photo_dir.exists()}")
    
    if photo_dir.exists():
        images = []
        for ext in ['.jpg', '.jpeg', '.png', '.gif']:
            images.extend(list(photo_dir.glob(f'*{ext}')))
            images.extend(list(photo_dir.glob(f'*{ext.upper()}')))
        
        print(f"📸 Images trouvées ({len(images)}):")
        for img in images:
            print(f"   - {img.name} ({img.stat().st_size} bytes)")
    
    # Initialiser la base
    try:
        init_database()
    except Exception as e:
        print(f"⚠️ Note: {e}")
    
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 Serveur démarré sur http://localhost:{port}")
    print(f"🔗 Testez une image: http://localhost:{port}/static/photo/miss_1.jpg")
    app.run(host='0.0.0.0', port=port, debug=True)
else:
    print("🚀 Application chargée en production...")
    try:
        init_database()
    except Exception as e:
        print(f"⚠️ Note: {e}")
        
