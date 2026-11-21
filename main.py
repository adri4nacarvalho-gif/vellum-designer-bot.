import os
import asyncio
import logging
from threading import Thread
from urllib.parse import urlparse

import discord
from discord.ext import commands
from flask import Flask

logging.basicConfig(level=logging.INFO)
SERVIDOR_ID = 1521281343751983196
CANAL_PROJETOS = 1544588990139605002
CANAL_BRIEFING = 1548539092734582814
CANAL_CATALOGO = 1544406060180308008
LIDER_ID = 1018665053794357259
COR = 0xA78B70

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return 'VELLUM Designer Online', 200

def web_server():
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8080')))

def embed(titulo, descricao='', cor=COR):
    e = discord.Embed(title=titulo, description=descricao, color=cor)
    e.set_footer(text='VELLUM DESIGN ✦ Estrutura que organiza. Design que impressiona. Experiência que conecta.')
    return e

async def dm(user_id, message):
    try:
        u = await bot.fetch_user(int(user_id))
        await u.send(embed=message)
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException, ValueError, TypeError):
        logging.warning('Não foi possível enviar DM para %s', user_id)
        return False

async def canal(cid):
    c = bot.get_channel(cid)
    if c is None:
        try:
            c = await bot.fetch_channel(cid)
        except discord.HTTPException:
            return None
    return c

def equipe(interaction):
    return (interaction.user.id == LIDER_ID or
            isinstance(interaction.user, discord.Member) and
            interaction.user.guild_permissions.manage_guild)

def campo(e, nome):
    return next((f.value for f in e.fields if f.name == nome), None)

def status(e, valor):
    for i, f in enumerate(e.fields):
        if f.name == 'Status':
            e.set_field_at(i, name='Status', value=valor, inline=False)
            return

lock = asyncio.Lock()

class Pedido(discord.ui.Modal, title='VELLUM | Solicitar Projeto'):
    nome = discord.ui.TextInput(label='Nome do cliente', max_length=100)
    tipo = discord.ui.TextInput(label='Tipo de projeto', placeholder='Residencial, comercial, corporativo...', max_length=100)
    link = discord.ui.TextInput(label='Link do projeto', placeholder='https://...', max_length=500)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        url = str(self.link).strip()
        parsed = urlparse(url)
        if parsed.scheme not in ('https', 'http') or not parsed.netloc:
            return await interaction.followup.send('❌ Informe um link válido começando com https:// ou http://.', ephemeral=True)
        c = await canal(CANAL_PROJETOS)
        if c is None:
            return await interaction.followup.send('❌ Canal de solicitações indisponível.', ephemeral=True)
        e = embed('✦ VELLUM | Nova Solicitação', 'Uma nova solicitação aguarda avaliação da equipe.')
        for name, value in [('Cliente', str(self.nome)), ('Tipo de Projeto', str(self.tipo)),
                            ('Link do Projeto', url), ('Solicitante', interaction.user.mention),
                            ('ID do Cliente', str(interaction.user.id)), ('Status', '⏳ Em análise')]:
            e.add_field(name=name, value=value, inline=False)
        try:
            await c.send(embed=e, view=Decisao(), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return await interaction.followup.send('❌ Não foi possível registrar a solicitação.', ephemeral=True)
        conf = embed('✦ Solicitação Recebida', f'Olá, **{self.nome}**! Sua solicitação foi recebida.\n\n⏳ **Status: Em análise**\nAguarde a avaliação da equipe VELLUM.')
        await interaction.followup.send(embed=conf, ephemeral=True)
        await dm(interaction.user.id, conf)

class Recusa(discord.ui.Modal, title='VELLUM | Recusar Projeto'):
    nome = discord.ui.TextInput(label='Nome do responsável', max_length=100)
    motivo = discord.ui.TextInput(label='Motivo da recusa', style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, message_id, channel_id):
        super().__init__()
        self.message_id = message_id
        self.channel_id = channel_id

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        if not equipe(interaction):
            return await interaction.followup.send('❌ Sem permissão.', ephemeral=True)
        async with lock:
            c = await canal(self.channel_id)
            try:
                m = await c.fetch_message(self.message_id)
            except (AttributeError, discord.HTTPException):
                return await interaction.followup.send('❌ Solicitação não encontrada.', ephemeral=True)
            if not m.embeds or campo(m.embeds[0], 'Status') != '⏳ Em análise':
                return await interaction.followup.send('Esta solicitação já foi analisada.', ephemeral=True)
            e = m.embeds[0].copy()
            cliente = campo(e, 'ID do Cliente')
            status(e, '❌ Recusado')
            e.color = discord.Color.red()
            e.add_field(name='Responsável pela Recusa', value=str(self.nome), inline=False)
            e.add_field(name='Motivo da Recusa', value=str(self.motivo), inline=False)
            try:
                await m.edit(embed=e, view=None)
            except discord.HTTPException:
                return await interaction.followup.send('❌ Falha ao registrar recusa.', ephemeral=True)
        await dm(cliente, embed('✦ VELLUM | Projeto Recusado', f'Sua solicitação não foi aprovada.\n\n**Responsável:** {self.nome}\n**Motivo:** {self.motivo}', discord.Color.red()))
        await dm(LIDER_ID, embed('✦ VELLUM | Solicitação Recusada', f'**Cliente:** <@{cliente}>\n**Responsável:** {self.nome}\n**Motivo:** {self.motivo}\n**Solicitação:** {m.jump_url}', discord.Color.red()))
        await interaction.followup.send('❌ Recusa registrada. Notificações tentadas por DM.', ephemeral=True)

class Decisao(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Aprovar Projeto', style=discord.ButtonStyle.success, emoji='✅', custom_id='vellum:aprovar_projeto')
    async def aprovar(self, interaction, button):
        if not equipe(interaction):
            return await interaction.response.send_message('❌ Sem permissão para avaliar projetos.', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with lock:
            try:
                m = await interaction.channel.fetch_message(interaction.message.id)
            except discord.HTTPException:
                return await interaction.followup.send('❌ Solicitação não encontrada.', ephemeral=True)
            if not m.embeds or campo(m.embeds[0], 'Status') != '⏳ Em análise':
                return await interaction.followup.send('Esta solicitação já foi analisada.', ephemeral=True)
            e = m.embeds[0].copy()
            cliente = campo(e, 'ID do Cliente')
            status(e, '✅ Aprovado')
            e.color = discord.Color.green()
            e.add_field(name='Aprovado por', value=interaction.user.mention, inline=False)
            try:
                await m.edit(embed=e, view=None)
            except discord.HTTPException:
                return await interaction.followup.send('❌ Erro ao registrar aprovação.', ephemeral=True)
        await dm(cliente, embed('✦ VELLUM | Projeto Aprovado', 'Sua solicitação foi **aprovada**! A equipe da VELLUM Designer dará continuidade ao atendimento.', discord.Color.green()))
        await dm(LIDER_ID, embed('✦ VELLUM | Projeto Aprovado', f'**Cliente:** <@{cliente}>\n**Aprovado por:** {interaction.user.mention}\n**Solicitação:** {m.jump_url}', discord.Color.green()))
        await interaction.followup.send('✅ Projeto aprovado. Notificações tentadas por DM.', ephemeral=True)

    @discord.ui.button(label='Recusar Projeto', style=discord.ButtonStyle.danger, emoji='❌', custom_id='vellum:recusar_projeto')
    async def recusar(self, interaction, button):
        if not equipe(interaction):
            return await interaction.response.send_message('❌ Sem permissão.', ephemeral=True)
        if not interaction.message.embeds or campo(interaction.message.embeds[0], 'Status') != '⏳ Em análise':
            return await interaction.response.send_message('Esta solicitação já foi analisada.', ephemeral=True)
        await interaction.response.send_modal(Recusa(interaction.message.id, interaction.channel_id))

class Briefing(discord.ui.Modal, title='VELLUM | Briefing do Projeto'):
    atmosfera = discord.ui.TextInput(label='1. Atmosfera desejada', style=discord.TextStyle.paragraph, max_length=1000)
    paleta = discord.ui.TextInput(label='2. Paleta, materiais e acabamentos', style=discord.TextStyle.paragraph, max_length=1000)
    elementos = discord.ui.TextInput(label='3. Elementos obrigatórios e a evitar', style=discord.TextStyle.paragraph, max_length=1000)
    prioridades = discord.ui.TextInput(label='4. Prioridades do projeto', style=discord.TextStyle.paragraph, max_length=1000)
    adicionais = discord.ui.TextInput(label='5. Informações adicionais', style=discord.TextStyle.paragraph, max_length=1000, required=False)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        c = await canal(CANAL_BRIEFING)
        if c is None:
            return await interaction.followup.send('❌ Canal de briefing indisponível.', ephemeral=True)
        e = embed('📋 Novo Briefing Recebido', f'Um novo briefing foi enviado à VELLUM Design.\n\n👤 **CLIENTE**\nSolicitante: {interaction.user.mention}\n\n━━━━━━━━━━━━━━━━━━\n📐 **BRIEFING DO PROJETO**')
        for title, value in [('1. ATMOSFERA DESEJADA', self.atmosfera), ('2. PALETA, MATERIAIS E ACABAMENTOS', self.paleta),
                             ('3. ELEMENTOS OBRIGATÓRIOS E O QUE EVITAR', self.elementos), ('4. PRIORIDADES DO PROJETO', self.prioridades),
                             ('5. INFORMAÇÕES ADICIONAIS', self.adicionais)]:
            e.add_field(name=title, value=str(value) or 'Não informado', inline=False)
        e.add_field(name='━━━━━━━━━━━━━━━━━━', value='Briefing recebido pela VELLUM Design ✦', inline=False)
        try:
            await c.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            return await interaction.followup.send('❌ Não foi possível enviar o briefing.', ephemeral=True)
        await interaction.followup.send(embed=embed('✦ Briefing Recebido', 'Seu briefing foi enviado com sucesso à equipe da VELLUM Designer!'), ephemeral=True)

# CATÁLOGO OFICIAL: os valores abaixo foram fornecidos pela VELLUM.
CATALOGO = {
'🛋️ Design de Interiores': ('Projetos para residências, apartamentos, escritórios, lojas, restaurantes e espaços corporativos.', '''Projeto residencial completo — T$ 1.200.000
Projeto de ambiente residencial individual — T$ 400.000
Projeto comercial — T$ 1.500.000
Projeto corporativo — T$ 1.800.000
Layout de ambiente — T$ 250.000
Escolha e curadoria de mobiliário — T$ 200.000
Projeto de iluminação — T$ 300.000
Planejamento de marcenaria — T$ 400.000
Modelagem 3D — T$ 400.000 por ambiente
Renderização — T$ 200.000 por imagem'''),
'🏗️ Reforma e Renovação': ('Planejamento e modernização de ambientes existentes.', '''Projeto de reforma residencial — T$ 1.500.000
Projeto de reforma comercial — T$ 1.800.000
Retrofit — T$ 2.000.000
Redistribuição de ambiente — T$ 400.000
Atualização de acabamentos — T$ 300.000
Reforma estética — T$ 600.000'''),
'🌿 Ambientação Sensorial': ('Projetos focados na experiência e na construção da atmosfera do ambiente.', '''Ambientação sensorial completa — T$ 1.200.000
Projeto de iluminação sensorial — T$ 400.000
Desenvolvimento de paleta de cores — T$ 100.000
Projeto de aromatização — T$ 100.000
Direcionamento acústico — T$ 250.000
Curadoria de texturas — T$ 200.000
Decoração temática — T$ 600.000'''),
'🏢 Ambientação Institucional': ('Desenvolvimento de espaços voltados para empresas e instituições.', '''Projeto de escritório — T$ 1.500.000
Projeto de clínica — T$ 1.500.000
Projeto de hotel — T$ 2.500.000
Projeto para escola ou instituição de ensino — T$ 1.800.000
Projeto de recepção — T$ 600.000
Projeto de sala de espera — T$ 500.000
Desenvolvimento de identidade espacial — T$ 800.000'''),
'🌌 Ambientação Urbana': ('Projetos destinados a áreas externas, espaços coletivos e ambientes de convivência.', '''Projeto para praça — T$ 2.500.000
Projeto para boulevard — T$ 3.000.000
Área de convivência — T$ 1.500.000
Projeto paisagístico — T$ 1.000.000
Projeto de mobiliário urbano — T$ 800.000
Espaço comunitário — T$ 1.800.000

Projetos urbanos de grande extensão ou alta complexidade poderão receber orçamento específico.'''),
'✨ Consultoria Estética': ('Orientação especializada para transformar, harmonizar ou aprimorar ambientes.', '''Consultoria estética completa — T$ 500.000
Escolha de materiais — T$ 100.000
Desenvolvimento de paleta de cores — T$ 100.000
Consultoria de decoração — T$ 250.000
Consultoria de iluminação — T$ 250.000
Curadoria de mobiliário — T$ 200.000
Organização visual — T$ 150.000'''),
'📐 Projeto Personalizado': ('Projetos exclusivos desenvolvidos do zero de acordo com as necessidades do cliente.', '''Projeto personalizado — T$ 2.000.000
Conceito personalizado — T$ 400.000
Planta baixa — T$ 400.000
Layout humanizado — T$ 300.000
Modelagem 3D — T$ 400.000 por ambiente
Renderização fotorrealista — T$ 200.000 por imagem
Memorial descritivo — T$ 400.000
Apresentação final do projeto — T$ 300.000
Projeto personalizado completo — T$ 3.000.000'''),
'💻 Serviços Digitais Complementares': ('Serviços voltados à organização e à ambientação de espaços digitais no Discord.', '''Criação de categoria — T$ 50.000
Estruturação de canal — T$ 75.000
Ambientação temática de canal — T$ 100.000
Organização visual de categoria — T$ 100.000
Painel de boas-vindas — T$ 100.000
Sistema de atendimento ou tickets — T$ 200.000
Automação personalizada — T$ 300.000
Integração externa — T$ 300.000
Identidade visual completa para ambiente digital — T$ 500.000
Projeto completo de ambientação digital — T$ 1.000.000'''),
'🔄 Modificações': ('Valores para alterações realizadas em projetos já contratados.', '''**MODIFICAÇÕES SIMPLES**
Alteração de paleta de cores — T$ 50.000
Alteração de mobiliário — T$ 75.000
Alteração de decoração — T$ 75.000
Alteração de iluminação — T$ 100.000
Alteração de materiais ou acabamentos — T$ 100.000
Pequena alteração de layout — T$ 150.000

**MODIFICAÇÕES MÉDIAS**
Nova proposta para ambiente já desenvolvido — T$ 300.000
Alteração significativa de layout — T$ 400.000
Remodelagem de ambiente — T$ 600.000
Reformulação estética completa — T$ 600.000
Nova modelagem 3D — T$ 300.000
Nova renderização — T$ 200.000 por imagem

**MODIFICAÇÕES DE GRANDE PORTE**
Inclusão de novo ambiente ao projeto — T$ 400.000
Inclusão de novo setor ou área — T$ 800.000
Reformulação completa de projeto — 50% do valor original
Reinício do projeto após aprovação final — 75% do valor original'''),
'➕ Adições ao Projeto': ('Serviços que podem ser acrescentados posteriormente ao projeto originalmente contratado.', '''Ambiente adicional — T$ 400.000
Modelagem 3D adicional — T$ 300.000
Renderização adicional — T$ 200.000
Imagem panorâmica adicional — T$ 300.000
Memorial descritivo complementar — T$ 300.000
Curadoria adicional de mobiliário — T$ 200.000
Estudo adicional de iluminação — T$ 300.000
Projeto adicional de marcenaria — T$ 400.000
Ambientação temática complementar — T$ 400.000
Apresentação complementar — T$ 200.000'''),
'📊 Múltiplos Ambientes e Descontos': ('Desconto sobre os serviços principais contratados para projetos com múltiplos ambientes.', '''2 ambientes — 5% de desconto
3 ambientes — 7% de desconto
4 a 5 ambientes — 10% de desconto
6 ou mais ambientes — 15% de desconto

**NÃO SE APLICA DESCONTO A:**
Modificações posteriores
Adições realizadas após a contratação
Renderizações adicionais
Serviços digitais complementares
Automações
Integrações
Demandas especiais

O desconto máximo oferecido pela VELLUM é de 15%.'''),
'📌 Informações Importantes': ('Condições e observações do catálogo oficial.', '''Todos os valores apresentados são valores fechados para os serviços descritos.

Serviços adicionais possuem valores próprios e são cobrados separadamente.

Alterações realizadas após a aprovação de uma etapa serão cobradas conforme a tabela de modificações.

Alterações que modifiquem integralmente o conceito ou o escopo poderão ser classificadas como reformulação de projeto.

Projetos de grande porte ou com necessidades excepcionais poderão receber proposta específica.

Os valores poderão ser atualizados pela VELLUM em futuras revisões deste catálogo.

O prazo de desenvolvimento dependerá da quantidade e da complexidade dos serviços contratados.

**✦ OBSERVAÇÃO ✦**
Cada projeto é único.

A VELLUM Design desenvolve soluções de acordo com a identidade, as necessidades e os objetivos de cada cliente.

Este catálogo foi estruturado para oferecer maior transparência, permitindo que cada cliente saiba previamente o valor dos serviços, das adições e das possíveis modificações em seu projeto.''')
}

class SeletorCatalogo(discord.ui.Select):
    def __init__(self):
        opts = [discord.SelectOption(label=nome[:100], value=str(i), description='Consultar serviços e condições') for i, nome in enumerate(CATALOGO)]
        super().__init__(placeholder='✦ Selecione uma categoria do catálogo', min_values=1, max_values=1, options=opts, custom_id='vellum:categoria_catalogo')

    async def callback(self, interaction):
        nome = list(CATALOGO)[int(self.values[0])]
        descricao, itens = CATALOGO[nome]
        # Descrição de embeds Discord: limite de 4096 caracteres.
        e = embed(f'✦ {nome}', f'{descricao}\n\n━━━━━━━━━━━━━━━━━━\n**SERVIÇOS, VALORES E CONDIÇÕES**\n\n{itens}\n\n━━━━━━━━━━━━━━━━━━')
        await interaction.response.send_message(embed=e, ephemeral=True)

class MenuCatalogo(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SeletorCatalogo())

intents = discord.Intents.default()

class Vellum(commands.Bot):
    async def setup_hook(self):
        self.add_view(Decisao())
        self.add_view(MenuCatalogo())
        guild = discord.Object(id=SERVIDOR_ID)
        # Remove antigos comandos globais da aplicação (incluindo /catalog).
        # Não sincronize globais se outros sistemas usarem esta aplicação.
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        await self.tree.sync(guild=guild)

bot = Vellum(command_prefix='!', intents=intents)

@bot.tree.command(name='projeto', description='Solicite um projeto à VELLUM Designer', guild=discord.Object(id=SERVIDOR_ID))
async def projeto(interaction: discord.Interaction):
    await interaction.response.send_modal(Pedido())

@bot.tree.command(name='briefing', description='Envie o briefing do seu projeto à VELLUM Designer', guild=discord.Object(id=SERVIDOR_ID))
async def briefing(interaction: discord.Interaction):
    await interaction.response.send_modal(Briefing())

@bot.tree.command(name='catalogo', description='Explore o catálogo oficial da VELLUM Designer', guild=discord.Object(id=SERVIDOR_ID))
async def catalogo(interaction: discord.Interaction):
    if interaction.channel_id != CANAL_CATALOGO:
        return await interaction.response.send_message(f'📌 Utilize este comando no canal <#{CANAL_CATALOGO}>.', ephemeral=True)
    e = embed('╭── ✦ VELLUM DESIGN ✦ ──╮\nCATÁLOGO OFICIAL', 'Bem-vindo ao catálogo oficial da VELLUM Design.\n\nTransformamos ideias em ambientes únicos, funcionais e memoráveis, desenvolvendo cada projeto de acordo com a identidade, as necessidades e a experiência desejada pelo cliente.\n\nA VELLUM atua no desenvolvimento de projetos de design, ambientação e organização de espaços, aplicando princípios profissionais de estética, funcionalidade e experiência.\n\nNeste catálogo, você poderá conhecer nossas áreas de atuação, os serviços disponíveis e seus respectivos valores em **T$**.\n\n✦ **Escolha uma categoria no menu abaixo.**\n\nEstrutura que organiza.\nDesign que impressiona.\nExperiência que conecta.')
    await interaction.response.send_message(embed=e, view=MenuCatalogo(), ephemeral=False)

@bot.event
async def on_ready():
    logging.info('VELLUM conectada como %s', bot.user)

if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise RuntimeError('DISCORD_TOKEN ausente. Configure a chave no ambiente do Replit.')
    Thread(target=web_server, daemon=True).start()
    bot.run(token)
