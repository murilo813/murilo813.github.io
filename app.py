from flask import Flask, render_template, request, redirect, flash, session, jsonify, send_from_directory
import gspread
import os
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import psycopg2
from datetime import date

app = Flask(__name__, template_folder=os.path.abspath('.'))  # A pasta atual será a pasta de templates
app.config['ENV'] = 'production'  # Define o ambiente como produção
app.config['DEBUG'] = False       # Certifique-se de que o modo debug está desativado
app.jinja_env.add_extension('jinja2.ext.do')  # Adicionando a extensão do Jinja
app.secret_key = os.getenv('FLASK_SECRET_KEY')

# Função para carregar os usuários da planilha
def carregar_usuarios():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(os.getenv('GOOGLE_SHEET_CREDENTIALS'), scope)
    client = gspread.authorize(creds)
    sheet = client.open("USUARIOS").sheet1  # Nome da sua planilha
    dados = sheet.get_all_records()  # Pega todos os dados da planilha
    df = pd.DataFrame(dados)

    print(df.columns)

    # Verifica e manipula a coluna 'lojas', tratando valores como string
    if 'lojas' in df.columns:
        df['lojas'] = df['lojas'].apply(lambda x: [int(loja.strip()) for loja in str(x).split(',')] if pd.notna(x) else [])
        print(f"Loja(s) de acesso do usuário: {df['lojas'].iloc[0]}")  # Apenas para debug

    return df



# Função para carregar os atendimentos da planilha

def carregar_atendimentos(nome_cliente, cpfs_relacionados):
    print(f"Procurando atendimentos para o cliente: {nome_cliente} e CPFs relacionados: {cpfs_relacionados}")
    # Definir o escopo para a autenticação do Google Sheets
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    # Autenticar com as credenciais do Google
    creds = ServiceAccountCredentials.from_json_keyfile_name('scripts/site-438020-5907dbb8fe0c.json', scope)
    client = gspread.authorize(creds)
    
    # Abrir a planilha e a aba de atendimentos
    sheet = client.open("USUARIOS").worksheet("ATENDIMENTOS")

    
    
    try:
        # Carregar todos os dados da planilha
        dados = sheet.get_all_records(value_render_option='FORMATTED_VALUE')
        print("Dados carregados da planilha:", dados)
        
        

        atendimentos_filtrados = [
            registro for registro in dados
            if str(registro.get('cpf_cnpj_cliente', '')).zfill(11) == nome_cliente or
               (cpfs_relacionados and str(registro['cpf_cnpj_cliente']).zfill(11) in cpfs_relacionados)
        ]

        print(f"Atendimentos filtrados antes de retornar: {atendimentos_filtrados}")  # Verifique aqui



        print(f"Atendimentos retornados: {atendimentos_filtrados}")

        return atendimentos_filtrados
    except Exception as e:
        print(f"Erro na consulta: {e}")
        return render_template('consulta.html')



# Rota inicial (index)
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':  # Só processa o formulário quando for POST
        nome = request.form.get('username', '').strip()  # Remove espaços em branco
        senha = request.form.get('password', '').strip()  # Remove espaços em branco

        # Carrega os usuários da planilha
        df_usuarios = carregar_usuarios()

        # Verifica se existe um usuário com o nome e senha fornecidos
        usuario_encontrado = df_usuarios[
            (df_usuarios['nome'] == nome) & (df_usuarios['senha'] == senha)
        ]

        if not usuario_encontrado.empty:  # Se o usuário foi encontrado
            senha_usuario = usuario_encontrado['senha'].iloc[0]
            
            if pd.isna(senha_usuario):
                flash("Senha não disponível para este usuário.")
                return redirect('/login')

            if senha_usuario == senha:
                lojas_acesso = usuario_encontrado['lojas'].iloc[0]  # Lista de lojas
                session['usuario'] = nome  # Guarda o nome do usuário na sessão
                session['lojas_acesso'] = lojas_acesso  # Guarda as lojas no session
                print(f"Loja(s) de acesso do usuário: {lojas_acesso}")
                print(f"Usuário logado com acesso às lojas: {lojas_acesso}")
                return redirect('consulta_cliente')
            else:
                flash('Nome de usuário ou senha incorretos. Por favor, tente novamente.')
                return redirect('/login')

        else:
            flash('Nome de usuário ou senha incorretos. Por favor, tente novamente.')
            return redirect('/login')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()  # Limpa os dados da sessão ao fazer logout
    return render_template('index.html')







# Função para criar conexão com o banco de dados
def criar_conexao():
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )

# Rota para consulta de cliente por nome
@app.route('/consulta', methods=['GET', 'POST'])
def consulta_cliente():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()  # Obtém o nome do formulário
        cpf_selecionado = request.form.get('cpf_selecionado', '').strip()  # CPF do cliente selecionado
        data_hoje = date.today().strftime('%Y-%m-%d')
        lojas_acesso = session.get('lojas_acesso', [])  # Obtém as lojas de acesso do usuário

        try:
            conexao = criar_conexao()
            cursor = conexao.cursor()
            atendimentos = []

            # Caso um CPF seja selecionado, busca os detalhes do cliente e suas notas
            if cpf_selecionado:
                query_cliente = """
                    SELECT cpf_cnpj_cliente, nome_cliente, responsavel, bairro
                    FROM clientes 
                    WHERE cpf_cnpj_cliente = %s AND ativo = 'S'
                """
                cursor.execute(query_cliente, (cpf_selecionado,))
                cliente = cursor.fetchone()
                
                cpfs_relacionados = []
                clientes_relacionados = []  # Certifique-se de inicializar antes de usá-la

                # Se o cliente for encontrado, adiciona o CPF do cliente principal
                if cliente:  
                    cpfs_relacionados.append(cliente[0])

                    # Adicione aqui a lógica para preencher a lista clientes_relacionados
                    query_responsaveis = """
                        SELECT cpf_cnpj_cliente, nome_cliente, bairro
                        FROM clientes
                        WHERE responsavel = %s AND ativo = 'S' AND bairro = %s
                    """
                    cursor.execute(query_responsaveis, (cliente[2], cliente[3]))  # cliente[3] seria o bairro do cliente principal
                    clientes_relacionados = cursor.fetchall()

                    # Preenche cpfs_relacionados com o CPF do cliente principal e os clientes relacionados
                    cpfs_relacionados = [cliente[0]]  # Inclui o CPF do cliente principal
                    for cliente_relacionado in clientes_relacionados:
                        if cliente_relacionado[2] == cliente[3]:  # cliente[3] é o bairro do cliente principal
                            cpfs_relacionados.append(cliente_relacionado[0])

                    print(f"CPFs relacionados: {cpfs_relacionados}")

                    # Chama a função que carrega os atendimentos filtrados
                    atendimentos_filtrados = carregar_atendimentos(cpf_selecionado, cpfs_relacionados)
                    print(f"Atendimentos carregados: {atendimentos_filtrados}")
                

                
                    # Verifique se o valor é vazio logo após a atribuição
                    if not atendimentos_filtrados:
                        print("Atendimentos filtrados estão vazios após a chamada para carregar_atendimentos.")


                if cliente:  # Garante que o cliente foi encontrado
                    print(f"ATETESTE:{atendimentos}")  # Verifique o que está sendo carregado aqui
                    query_notas = """
                        SELECT DISTINCT
                            cr.empresa,
                            cr.nota,
                            cr.data_venda,
                            cr.data_vencimento,
                            cr.valor_original,
                            cr.saldo_devedor
                        FROM 
                            contas_a_receber cr
                        WHERE 
                            cr.cpf_cnpj_cliente = %s
                            AND cr.data_base = %s
                    """

                    cpf_cliente = cliente[0]  # CPF do cliente
                    nome_cliente = cliente[1]  # Nome do cliente
                    responsavel = cliente[2]
                    bairro_cliente = cliente[3]  # A variável 'bairro_cliente' deve conter o valor do bairro do cliente

                    
                    cliente_detalhes = {
                        "cpf": cliente[0],
                        "nome": cliente[1],
                        "notas": [],
                        "atendimentos": atendimentos_filtrados  # Passando os atendimentos encontrados
                    }
                    

 

                    atendimentos_combinados = []
                    # Para cada cpf relacionado, combine os atendimentos
                    for cpf in cpfs_relacionados:
                        # Filtra os atendimentos por cpf
                        atendimentos_cliente = [atendimento for atendimento in atendimentos if atendimento['cpf_cnpj_cliente'] == cpf]
                        atendimentos_combinados.extend(atendimentos_cliente)

                     # Carregar os atendimentos de acordo com o CPF do cliente e seus relacionados
                    atendimentos_combinados = carregar_atendimentos(cpf_cliente, cpfs_relacionados)
                    cliente_detalhes["atendimentos"] = atendimentos_combinados


                    # Remove duplicatas nos atendimentos
                    atendimentos_deduplicados = list({f"{atd['cpf_cnpj_cliente']}_{atd['data_atendimento']}": atd for atd in atendimentos_combinados}.values())

                    # Atualiza o cliente_detalhes para incluir os atendimentos deduplicados
                    cliente_detalhes["atendimentos"] = atendimentos_deduplicados

                    cursor.execute(query_notas, (cpf_selecionado, data_hoje))
                    notas = cursor.fetchall()

                    if notas:
                        empresas_cliente = set([nota[0] for nota in notas])  # Extrai todas as empresas do cliente
                        lojas_acesso_str = [str(loja).strip() for loja in lojas_acesso]
                        empresas_acesso = [str(empresa).strip() for empresa in empresas_cliente]

                    
                        if not any(empresa in lojas_acesso_str for empresa in empresas_acesso):
                            flash(f"Você não tem acesso a nenhuma loja/empresa do cliente {nome_cliente}.")
                            return render_template('consulta.html')

                        # Caso tenha permissão para a empresa, exibe as notas
                    cliente_detalhes = {
                        "cpf": cpf_cliente,
                        "nome": nome_cliente,
                        "notas": [
                            {
                                "empresa": nota[0],
                                "nota": nota[1],
                                "data_venda": nota[2],
                                "data_vencimento": nota[3],
                                "valor_original": nota[4],
                                "saldo_devedor": nota[5],
                            }
                            for nota in notas
                        ],
                    }
                    

                    for clientes_relacionado in clientes_relacionados:
                        cpf_selecionado = clientes_relacionado[0]
                        nome_relacionado = clientes_relacionado[1]

                        cursor.execute(query_notas, (cpf_selecionado, data_hoje))
                        notas_relacionadas = cursor.fetchall()

                        clientes_relacionados_detalhes = []  # Inicializa a lista vazia

                        for clientes_relacionado in clientes_relacionados:
                            cpf_selecionado = clientes_relacionado[0]
                            nome_relacionado = clientes_relacionado[1]

                            cursor.execute(query_notas, (cpf_selecionado, data_hoje))
                            notas_relacionadas = cursor.fetchall()

                            # Adiciona os detalhes dos clientes relacionados à lista
                            clientes_relacionados_detalhes.append({
                                "cpf": cpf_selecionado,
                                "nome": nome_relacionado,
                                "notas": [
                                    {
                                        "empresa": nota[0],
                                        "nota": nota[1],
                                        "data_venda": nota[2],
                                        "data_vencimento": nota[3],
                                        "valor_original": nota[4],
                                        "saldo_devedor": nota[5],
                                    }
                                    for nota in notas_relacionadas
                                ],
                            })

                    # Deduplicar as notas no backend para evitar duplicações
                    notas_unicas = {nota['nota']: nota for nota in cliente_detalhes['notas']}.values()
                    cliente_detalhes['notas'] = list(notas_unicas)  # Atualiza com os dados deduplicados


                        
                    total_a_receber = sum(
                        nota["saldo_devedor"] for nota in cliente_detalhes["notas"]
                    )  

                    total_a_receber += sum(
                        nota["saldo_devedor"]
                        for cliente_relacionado in clientes_relacionados_detalhes
                        if cliente_relacionado["cpf"] != cliente_detalhes["cpf"]  # Somente para CPFs relacionados que não são do mesmo cliente
                        for nota in cliente_relacionado["notas"]
                    )

                    clientes_relacionados_detalhes = [
                        cliente for cliente in clientes_relacionados_detalhes
                        if cliente["cpf"] != cliente_detalhes["cpf"]  # Excluindo o mesmo CPF
                    ]


                    cliente_detalhes['total_a_receber'] = total_a_receber

                    clientes = [(cpf_cliente, nome_cliente)] + clientes_relacionados

                    print("Antes de retornar para o template:", atendimentos_filtrados)
                    return render_template('consulta.html', 
                        clientes=clientes, 
                        cliente_detalhes=cliente_detalhes,
                        clientes_relacionados_detalhes=clientes_relacionados_detalhes,
                        atendimentos=atendimentos_filtrados
                    )



                flash("Cliente não encontrado para o CPF selecionado.")
                return render_template('consulta.html')

            # Pesquisa inicial por nome
            query = """
                SELECT cpf_cnpj_cliente, nome_cliente, responsavel, bairro
                FROM clientes 
                WHERE (nome_cliente ILIKE %s OR responsavel ILIKE %s) AND ativo = 'S'
            """
            cursor.execute(query, (f"%{nome}%", f"%{nome}%"))
            clientes = cursor.fetchall()

            clientes_unicos = []
            seen = set()

            for cpf, nome, responsavel, bairro in clientes:
                chave_cliente = (nome, bairro)
                if chave_cliente not in seen:
                    seen.add(chave_cliente)
                    clientes_unicos.append((cpf, nome, responsavel, bairro))
                    
            if clientes_unicos:
                return render_template('consulta.html', clientes=clientes_unicos, atendimentos=atendimentos)

            flash("Cliente não encontrado.")
            return render_template('consulta.html')

        except Exception as e:
            print(f"Erro na consulta: {e}")
            flash("Ocorreu um erro na consulta.")
            return render_template('consulta.html')

        finally:
            if 'conexao' in locals():
                conexao.close()

    return render_template('consulta.html')


@app.route('/add_observation', methods=['POST'])
def adicionar_observacao():
    scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

    # Testa autenticação e acesso à planilha
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name('scripts/site-438020-5907dbb8fe0c.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open("USUARIOS").worksheet("ATENDIMENTOS")
        print("Planilha acessada com sucesso!")
    except gspread.SpreadsheetNotFound:
        print("Planilha não encontrada. Verifique o nome ou as permissões.")
        return jsonify({"error": "Planilha não encontrada. Verifique o nome ou as permissões."}), 404
    except Exception as e:
        print(f"Erro na autenticação ou no acesso à planilha: {e}")
        return jsonify({"error": str(e)}), 500

    # Continuação da lógica principal
    try:
        print("Dados recebidos:", request.form)

        # Capturar dados do formulário
        cliente_valor = request.form.get('cliente')
        if '|' in cliente_valor:
            cpf_cnpj_cliente, nome_cliente = cliente_valor.split('|')  # Extrai CPF e Nome
        else:
            return jsonify({"error": "Formato inválido para cliente"}), 400
            
        observacao = request.form.get('observation')
        data_atendimento = request.form.get('date')

        print(f"Observação: {observacao}, Data: {data_atendimento}, Nome: {nome_cliente}, CPF/CNPJ: {cpf_cnpj_cliente}")

        if not observacao or not data_atendimento or not nome_cliente or not cpf_cnpj_cliente:
            print("Erro: Dados incompletos")
            return jsonify({"error": "Dados incompletos"}), 400

        usuario_logado = session.get('usuario')  # Supondo que você use session['usuario']

        if not usuario_logado:
            return jsonify({"error": "Usuário não logado"}), 400  # Garantir que o usuário esteja logado

        print(f"Usuário logado: {usuario_logado}")

        # Autenticar Google Sheets
        colunas = sheet.row_values(1)  # Captura os títulos da primeira linha

        # Obter índices das colunas
        indice_data = colunas.index('data_atendimento') + 1
        indice_obs = colunas.index('observacao') + 1
        indice_nome = colunas.index('nome_cliente') + 1
        indice_cpf = colunas.index('cpf_cnpj_cliente') + 1
        indice_usuario = colunas.index('usuario') + 1  # Índice da coluna 'usuario'

         # Adicionar nova linha na planilha
        nova_linha = [''] * max(indice_data, indice_obs, indice_nome, indice_cpf, indice_usuario)
        nova_linha[indice_nome - 1] = nome_cliente
        nova_linha[indice_cpf - 1] = cpf_cnpj_cliente
        nova_linha[indice_data - 1] = data_atendimento
        nova_linha[indice_obs - 1] = observacao
        nova_linha[indice_usuario - 1] = usuario_logado

        sheet.append_row(nova_linha, value_input_option="USER_ENTERED")

        print(f"Observação adicionada com sucesso: {nova_linha}")
        return jsonify({"success": "Observação adicionada com sucesso!"}), 200

    except Exception as e:
        # Caso ocorra um erro, exibir a mensagem no JSON
        print(f"Erro ao adicionar observação: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=False)






