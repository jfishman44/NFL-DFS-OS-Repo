import json5 as json
import csv
import os
import datetime
import pytz
import timedelta
import numpy as np
import pulp as plp
import itertools
from random import shuffle, choice

class NFL_Showdown_Optimizer:
    site = None
    config = None
    problem = None
    output_dir = None
    num_lineups = None
    num_uniques = None
    team_list = []
    players_by_team = {}
    lineups = []
    player_dict = {}
    at_least = {}
    at_most = {}
    team_limits = {}
    matchup_limits = {}
    matchup_at_least = {}
    stack_rules = {}
    global_team_limit = 5
    use_double_te = True
    projection_minimum = 0
    randomness_amount = 0
    default_qb_var = 0.4
    default_skillpos_var = 0.5
    default_def_var = 0.5
    team_rename_dict = {
        "LA": "LAR"
    }

    def __init__(self, site=None, num_lineups=0, num_uniques=1):
        self.site = site
        self.num_lineups = int(num_lineups)
        self.num_uniques = int(num_uniques)
        self.load_config()
        self.load_rules()

        self.problem = plp.LpProblem('NFL', plp.LpMaximize)

        projection_path = os.path.join(os.path.dirname(
            __file__), '../{}_data/{}'.format(site, self.config['projection_path']))
        self.load_projections(projection_path)

        player_path = os.path.join(os.path.dirname(
            __file__), '../{}_data/{}'.format(site, self.config['player_path']))
        self.load_player_ids(player_path)
        

    def flatten(self, list):
        return [item for sublist in list for item in sublist]

    # make column lookups on datafiles case insensitive
    def lower_first(self, iterator):
        return itertools.chain([next(iterator).lower()], iterator)

    # Load config from file
    def load_config(self):
        with open(os.path.join(os.path.dirname(__file__), '../config.json')) as json_file:
            self.config = json.load(json_file)

    # Load player IDs for exporting
    def load_player_ids(self, path):
        with open(path) as file:
            reader = csv.DictReader(self.lower_first(file))
            for row in reader:
                name_key = 'name' if self.site == 'dk' else 'nickname'
                player_name = row[name_key].replace('-', '#').lower().strip()
                position = row['roster position'].split('/')[0] if self.site == 'dk' else row['position']
                if position == 'D' and self.site == 'fd':
                    position = 'DST'
                team = row['teamabbrev'] if self.site == 'dk' else row['team']
                if (player_name, position, team) in self.player_dict:
                    if self.site == 'dk':
                        matchup = row['game info'].split(' ')[0]
                        teams = matchup.split('@')
                        opponent = teams[0] if teams[0] != team else teams[1]
                    elif self.site == 'fd':
                        matchup = row['game']
                        teams = matchup.split('@')
                        opponent = row['opponent']
                    self.player_dict[(player_name, position, team)]['Opponent'] = opponent
                    self.player_dict[(player_name, position, team)]['Matchup'] = matchup
                    if self.site == 'dk':
                        self.player_dict[(player_name, position, team)]['ID'] = int(
                            row['id'])
                    else:
                        self.player_dict[(player_name, position, team)]['ID'] = row['id']

    def load_rules(self):
        self.at_most = self.config["at_most"]
        self.at_least = self.config["at_least"]
        self.team_limits = self.config["team_limits"]
        self.global_team_limit = int(self.config["global_team_limit"])
        self.projection_minimum = int(self.config["projection_minimum"])
        self.randomness_amount = float(self.config["randomness"])
        self.use_double_te = bool(self.config["use_double_te"])
        self.stack_rules = self.config["stack_rules"]
        self.matchup_at_least = self.config["matchup_at_least"]
        self.matchup_limits = self.config["matchup_limits"]
        self.default_qb_var = self.config["default_qb_var"] if 'default_qb_var' in self.config else 0.333
        self.default_skillpos_var = self.config["default_skillpos_var"] if 'default_skillpos_var' in self.config else 0.5
        self.default_def_var = self.config["default_def_var"] if 'default_def_var' in self.config else 0.5

    # Load projections from file
    def load_projections(self, path):
        # Read projections into a dictionary
        with open(path, encoding='utf-8-sig') as file:
            reader = csv.DictReader(self.lower_first(file))
            for row in reader:
                player_name = row['name'].replace('-', '#').lower().strip()
                position = row['position']
                if position == 'D':
                    position = 'DST'
                    
                team = row['team']
                if team in self.team_rename_dict:
                    team = self.team_rename_dict[team]
                    
                if team == 'JAX' and self.site == 'fd':
                    team = 'JAC'
                
                stddev = row['stddev'] if 'stddev' in row else 0
                if stddev == '':
                    stddev = 0
                else:
                    stddev = float(stddev)
                
                if float(row['fpts']) < self.projection_minimum and row['position'] != 'DST':
                    continue
               
                if stddev <= 0:
                    if position == 'QB':
                        stddev = float(row['fpts']) * self.default_qb_var
                    elif position == 'DST':
                        stddev = float(row['fpts']) * self.default_def_var
                    else:
                        stddev = float(row['fpts']) * self.default_skillpos_var
                        
                ceiling = float(row['ceiling']) if 'ceiling' in row else float(row['fpts']) + stddev
                if ceiling == '':
                    ceiling = float(row['fpts']) + stddev
                
                ownership = float(row['own%']) if 'own%' in row and row['own%'] != '' else 0.1
                cptn_ownership = float(row['cptown%']) if 'cptown%' in row and row['cptown%'] != '' else 0.1
                if cptn_ownership == 0.1:
                    cptn_ownership = 0.5 * ownership
                        
                # Assign FLEX then CPTN position for showdown
                self.player_dict[(player_name, 'FLEX', team)] = {
                    'Fpts': float(row['fpts']),
                    'RosterPosition': 'FLEX',
                    'NormalPosition': position,
                    'ID': 0,
                    'Salary': int(row['salary'].replace(',','')),
                    'Name': row['name'],
                    'Matchup': '',
                    'Team': team,
                    'Ownership': ownership,
                    'Ceiling': float(ceiling),
                    'StdDev': stddev,
                }
                self.player_dict[(player_name, 'CPT', team)] = {
                    'Fpts': 1.5 * float(row['fpts']),
                    'RosterPosition': 'CPT',
                    'NormalPosition': position,
                    'ID': 0,
                    'Salary': 1.5 * int(row['salary'].replace(',','')),
                    'Name': row['name'],
                    'Matchup': '',
                    'Team': team,
                    'Ownership': cptn_ownership,
                    'Ceiling': 1.5 * float(ceiling),
                    'StdDev': 1.5 * stddev,
                }
                
                if team not in self.team_list:
                    self.team_list.append(team)
                    
                if team not in self.players_by_team:
                    self.players_by_team[team] = {
                        'QB': [], 'RB': [], 'WR': [], 'TE': [], 'DST': [], 'K': [],
                    }
                
                self.players_by_team[team][position].append(self.player_dict[(player_name, 'CPT', team)])
                self.players_by_team[team][position].append(self.player_dict[(player_name, 'FLEX', team)])

    def optimize(self):
        # Setup our linear programming equation - https://en.wikipedia.org/wiki/Linear_programming
        # We will use PuLP as our solver - https://coin-or.github.io/pulp/

        # We want to create a variable for each roster slot.
        # There will be an index for each player and the variable will be binary (0 or 1) representing whether the player is included or excluded from the roster.
        lp_variables = {self.player_dict[(player, pos_str, team)]['ID']: plp.LpVariable(
            str(self.player_dict[(player, pos_str, team)]['ID']), cat='Binary'
            ) for (player, pos_str, team) in self.player_dict}

        # set the objective - maximize fpts & set randomness amount from config
        if self.randomness_amount != 0:
            self.problem += plp.lpSum(np.random.normal(self.player_dict[(player, pos_str, team)]['Fpts'],
                                                        (self.player_dict[(player, pos_str, team)]['StdDev'] * self.randomness_amount / 100))
                                        * lp_variables[self.player_dict[(player, pos_str, team)]['ID']]
                             for (player, pos_str, team) in self.player_dict), 'Objective'
        else:
            self.problem += plp.lpSum(self.player_dict[(player, pos_str, team)]['Fpts'] * lp_variables[self.player_dict[(player, pos_str, team)]['ID']]
                             for (player, pos_str, team) in self.player_dict), 'Objective'
        
        # Set the salary constraints
        max_salary = 50000 if self.site == 'dk' else 60000
        min_salary = 45000 if self.site == 'dk' else 55000
        self.problem += plp.lpSum(self.player_dict[(player, pos_str, team)]['Salary'] *
                                  lp_variables[self.player_dict[(player, pos_str, team)]['ID']] for (player, pos_str, team) in self.player_dict) <= max_salary, 'Max Salary'
        self.problem += plp.lpSum(self.player_dict[(player, pos_str, team)]['Salary'] *
                                  lp_variables[self.player_dict[(player, pos_str, team)]['ID']] for (player, pos_str, team) in self.player_dict) >= min_salary, 'Min Salary'

        # Address limit rules if any
        for limit, groups in self.at_least.items():
            for group in groups:
                tuple_name_list = []
                for key, value in self.player_dict.items():
                    if value['Name'] in group:
                        tuple_name_list.append(key)
                        
                self.problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]['ID']]
                                          for (player, pos_str, team) in tuple_name_list) >= int(limit), f'At least {limit} players {tuple_name_list}'

        for limit, groups in self.at_most.items():
            for group in groups:
                tuple_name_list = []
                for key, value in self.player_dict.items():
                    if value['Name'] in group:
                        tuple_name_list.append(key)
                        
                self.problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]['ID']]
                                          for (player, pos_str, team) in tuple_name_list) <= int(limit), f'At most {limit} players {tuple_name_list}'


        # Address team limits
        for team, limit in self.team_limits.items():
            self.problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]['ID']]
                                      for (player, pos_str, team) in self.player_dict if self.player_dict[(player, pos_str, team)]['Team'] == team) <= int(limit), f'Team limit {team} {limit}'

        if self.global_team_limit is not None:
            for limit_team in self.team_list:
                self.problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]['ID']]
                                          for (player, pos_str, team) in self.player_dict if self.player_dict[(player, pos_str, team)]['Team'] == limit_team) <= int(self.global_team_limit), f'Global team limit {limit_team} {self.global_team_limit}'
                
        # Address matchup limits
        if self.matchup_limits is not None:
            for matchup, limit in self.matchup_limits.items():
                players_in_game = []
                for key, value in self.player_dict.items():
                    if value['Matchup'] == matchup:
                        players_in_game.append(key)
                self.problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]['ID']] for (player, pos_str, team) in players_in_game) <= int(limit), f'Matchup limit {matchup} {limit}'
        
        if self.matchup_at_least is not None:
            for matchup, limit in self.matchup_limits.items():
                players_in_game = []
                for key, value in self.player_dict.items():
                    if value['Matchup'] == matchup:
                        players_in_game.append(key)
                self.problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]['ID']] for (player, pos_str, team) in players_in_game) >= int(limit), f'Matchup at least {matchup} {limit}'
                    
        # Address stack rules
        for rule_type in self.stack_rules:
            for rule in self.stack_rules[rule_type]:
                if rule_type == 'pair':
                    pos_key = rule['key']
                    stack_positions = rule['positions']
                    count = rule['count']
                    stack_type = rule['type']
                    excluded_teams = rule['exclude_teams']
                    
                    # Iterate each team, less excluded teams, and apply the rule for each key player pos
                    for team in self.players_by_team:
                        if team in excluded_teams:
                            continue
                        
                        pos_key_player = self.players_by_team[team][pos_key][0]
                        opp_team = pos_key_player['Opponent']
                        
                        stack_players = []
                        if stack_type == 'same-team':
                            for pos in stack_positions:
                                stack_players.append(self.players_by_team[team][pos])
                                
                        elif stack_type == 'opp-team':
                            for pos in stack_positions:
                                stack_players.append(self.players_by_team[opp_team][pos])
                                
                        elif stack_type == 'same-game':
                            for pos in stack_positions:
                                stack_players.append(self.players_by_team[team][pos])
                                stack_players.append(self.players_by_team[opp_team][pos])
                                
                        stack_players = self.flatten(stack_players)
                        # player cannot exist as both pos_key_player and be present in the stack_players
                        stack_players = [
                            p for p in stack_players 
                            if not (p['Name'] == pos_key_player['Name'] and p['Position'] == pos_key_player['Position'] and p['Team'] == pos_key_player['Team'])
                        ]
                        pos_key_player_tuple = None
                        stack_players_tuples = []
                        for key, value in self.player_dict.items():
                            if value['Name'] == pos_key_player['Name'] and value['RosterPosition'] == pos_key_player['RosterPosition'] and value['Team'] == pos_key_player['Team']:
                                pos_key_player_tuple = key
                            elif (value['Name'], value['RosterPosition'], value['Team']) in [(player['Name'], player['RosterPosition'], player['Team']) for player in stack_players]:
                                stack_players_tuples.append(key)
                        
                        # CPT pos key player cannot be stacked with other CPTs
                        for (name, position, team) in stack_players_tuples:
                            # if cpt position, remove them from the list 
                            if position == 'CPT':
                                stack_players_tuples.remove((name, position, team))
                            
                        # [sum of stackable players] + -n*[stack_player] >= 0
                        self.problem += plp.lpSum([lp_variables[self.player_dict[player_tuple]['ID']] for player_tuple in stack_players_tuples] 
                                                  + [-count*lp_variables[self.player_dict[pos_key_player_tuple]['ID']]]) >= 0, f'Stack rule {pos_key_player_tuple} {stack_players_tuples} {count}'
                        
                elif rule_type == 'limit':
                    limit_positions = rule['positions'] # ["RB"]
                    stack_type = rule['type']
                    count = rule['count']
                    excluded_teams = rule['exclude_teams']
                    if 'unless_positions' in rule or 'unless_type' in rule:
                        unless_positions = rule['unless_positions']
                        unless_type = rule['unless_type']
                    else:
                        unless_positions = None
                        unless_type = None
                    
                    
                    # Iterate each team, less excluded teams, and apply the rule for each key player pos
                    for team in self.players_by_team:
                        opp_team = self.players_by_team[team]['QB'][0]['Opponent']
                        if team in excluded_teams:
                            continue
                        limit_players = []
                        if stack_type == 'same-team':
                            for pos in limit_positions:
                                limit_players.append(self.players_by_team[team][pos])
                                
                        elif stack_type == 'opp-team':
                            for pos in limit_positions:
                                limit_players.append(self.players_by_team[opp_team][pos])
                                
                        elif stack_type == 'same-game':
                            for pos in limit_positions:
                                limit_players.append(self.players_by_team[team][pos])
                                limit_players.append(self.players_by_team[opp_team][pos])
                                
                        limit_players = self.flatten(limit_players)
                        if unless_positions is None or unless_type is None:
                            # [sum of limit players] + <= n
                            limit_players_tuples = []
                            for key, value in self.player_dict.items():
                                if (value['Name'], value['RosterPosition'], value['Team']) in [(player['Name'], player['RosterPosition'], player['Team']) for player in limit_players]:
                                    limit_players_tuples.append(key)
                                
                            self.problem += plp.lpSum([lp_variables[self.player_dict[player_tuple]['ID']] for player_tuple in limit_players_tuples]) <= int(count), f'Limit rule {limit_players_tuples} {count}'
                        else:
                            unless_players = []
                            if unless_type == 'same-team':
                                for pos in unless_positions:
                                    unless_players.append(self.players_by_team[team][pos])
                            elif unless_type == 'opp-team':
                                for pos in unless_positions:
                                    unless_players.append(self.players_by_team[opp_team][pos])
                            elif unless_type == 'same-game':
                                for pos in unless_positions:
                                    unless_players.append(self.players_by_team[team][pos])
                                    unless_players.append(self.players_by_team[opp_team][pos])
                                    
                            unless_players = self.flatten(unless_players)
                            
                            # player cannot exist as both limit_players and unless_players
                            unless_players = [
                                p for p in unless_players
                                if not any(
                                    p['Name'] == key_player['Name'] and p['Position'] == key_player['Position'] and p['Team'] == key_player['Team'] 
                                    for key_player in limit_players
                                )
                                
                            ]
                            
                            limit_players_tuples = []
                            unless_players_tuples = []
                            for key, value in self.player_dict.items():
                                if (value['Name'], value['RosterPosition'], value['Team']) in [(player['Name'], player['RosterPosition'], player['Team']) for player in limit_players]:
                                    limit_players_tuples.append(key)
                                elif (value['Name'], value['RosterPosition'], value['Team']) in [(player['Name'], player['RosterPosition'], player['Team']) for player in unless_players]:
                                    unless_players_tuples.append(key)
                                    
                            # [sum of limit players] + -count(unless_players)*[unless_players] <= n
                            self.problem += plp.lpSum([lp_variables[self.player_dict[player_tuple]['ID']] for player_tuple in limit_players_tuples] 
                                        - int(count) * plp.lpSum([lp_variables[self.player_dict[player_tuple]['ID']] for player_tuple in unless_players_tuples])) <= int(count), f'Limit rule {limit_players_tuples} unless {unless_players_tuples} {count}'
                        
        # Need exactly 1 CPT
        captain_tuples = [(player, pos_str, team) for (player, pos_str, team) in self.player_dict if pos_str == 'CPT']
        self.problem += plp.lpSum(lp_variables[self.player_dict[cpt_tuple]['ID']] for cpt_tuple in captain_tuples) == 1, f'CPT == 1'
        
        # Need exactly 5 FLEX
        flex_tuples = [(player, pos_str, team) for (player, pos_str, team) in self.player_dict if pos_str == 'FLEX']
        self.problem += plp.lpSum(lp_variables[self.player_dict[flex_tuple]['ID']] for flex_tuple in flex_tuples) == 5, f'FLEX == 5'
        
        # Max 5 players from one team
        for teamIdent in self.team_list:
            players_on_team = [(player, position, team) for (player, position, team) in self.player_dict if teamIdent == team]
            self.problem += plp.lpSum(lp_variables[self.player_dict[player_tuple]['ID']] for player_tuple in players_on_team) <= 5, f'Max 5 players from one team {teamIdent}'
            

        
        # Can't roster the same player as cpt and flex
        players_grouped_by_name = {}
        for (player, pos_str, team) in self.player_dict:
            if player in players_grouped_by_name:
                players_grouped_by_name[player].append((player, pos_str, team))
            else:
                players_grouped_by_name[player] = [(player, pos_str, team)]
                
        for _, tuple_list in players_grouped_by_name.items():
            self.problem += plp.lpSum(lp_variables[self.player_dict[player_tuple]['ID']] for player_tuple in tuple_list) <= 1, f'No player in both CPT and FLEX {tuple_list}'


        # Crunch!
        for i in range(self.num_lineups):
            try:
                self.problem.solve(plp.PULP_CBC_CMD(msg=0))
            except plp.PulpSolverError:
                print('Infeasibility reached - only generated {} lineups out of {}. Continuing with export.'.format(
                    len(self.num_lineups), self.num_lineups))

            # Get the lineup and add it to our list
            self.problem.writeLP('file.lp')
            player_ids = [player for player in lp_variables if lp_variables[player].varValue != 0]
            players = []
            for key, value in self.player_dict.items():
                if value['ID'] in player_ids:
                    players.append(key)
                    
            fpts_used = self.problem.objective.value()
            self.lineups.append((players, fpts_used))
            
            
            if i % 100 == 0:
                print(i)
                
            # Ensure this lineup isn't picked again
            self.problem += plp.lpSum(lp_variables[self.player_dict[player]['ID']] for player in players) <= len(players) - self.num_uniques, f'Lineup {i}'
           
            # Set a new random fpts projection within their distribution
            if self.randomness_amount != 0:
                self.problem += plp.lpSum(np.random.normal(self.player_dict[(player, pos_str, team)]['Fpts'],
                                                        (self.player_dict[(player, pos_str, team)]['StdDev'] * self.randomness_amount / 100))
                                        * lp_variables[self.player_dict[(player, pos_str, team)]['ID']]
                             for (player, pos_str, team) in self.player_dict), 'Objective'

    def output(self):
        print('Lineups done generating. Outputting.')
        
        # Sort each individual lineup so that 'CPT' player appears first
        for idx, lineup_tuple in enumerate(self.lineups):
            self.lineups[idx] = (sorted(lineup_tuple[0], key=lambda player: player[1] != 'CPT'), lineup_tuple[1])
            
        formatted_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename_out = f'../output/{self.site}_sd_optimal_lineups_{formatted_timestamp}.csv'
        out_path = os.path.join(os.path.dirname(__file__), filename_out)
        with open(out_path, 'w') as f:
            f.write(
                    'CPT,FLEX,FLEX,FLEX,FLEX,FLEX,Salary,Fpts Proj,Fpts Used,Ceiling,Own. Product,Own. Sum,STDDEV,Stack Type\n')
            for x, fpts_used in self.lineups:
                team_count = {}
                for t in self.team_list:
                    team_count[t] = [1 if t in self.player_dict[player]['Team'] else 0 for player in x].count(1)
                
                team_stack_string = ''
                for team, count in team_count.items():
                    team_stack_string += f'{count}|'
                    
                salary = sum(
                    self.player_dict[player]['Salary'] for player in x)
                fpts_p = sum(self.player_dict[player]['Fpts'] for player in x)
                own_s = sum(self.player_dict[player]['Ownership'] for player in x)
                own_p = np.prod([self.player_dict[player]['Ownership']/100 for player in x])
                ceil = sum([self.player_dict[player]['Ceiling'] for player in x])
                stddev = sum([self.player_dict[player]['StdDev'] for player in x])
                lineup_str = '{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{},{},{},{},{},{},{},{}'.format(
                    self.player_dict[x[0]]['Name'], self.player_dict[x[0]]['ID'],
                    self.player_dict[x[1]]['Name'], self.player_dict[x[1]]['ID'],
                    self.player_dict[x[2]]['Name'], self.player_dict[x[2]]['ID'],
                    self.player_dict[x[3]]['Name'], self.player_dict[x[3]]['ID'],
                    self.player_dict[x[4]]['Name'], self.player_dict[x[4]]['ID'],
                    self.player_dict[x[5]]['Name'], self.player_dict[x[5]]['ID'],
                    salary, round(
                        fpts_p, 2), round(fpts_used, 2), ceil, own_p, own_s, stddev, team_stack_string[:-1]
                )
                f.write('%s\n' % lineup_str)
            
        print('Output done.')
        
