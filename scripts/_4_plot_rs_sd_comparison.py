
import geopandas as gpd
import json 
import matplotlib.pyplot as plt  
import seaborn as sns 
import re
import math 
from scipy import stats
from functools import reduce
import sys 
import statsmodels.api as sa
import glob 
import scikit_posthocs as sp
import pandas as pd 
import geopandas as gpd 
import numpy as np 
import os 
import _pickle as cPickle
# from _4_process_rs_data import generate_output,combine_rs_snotel_annually,aggregate_dfs,merge_dfs,split_basins,combine_sar_data
import matplotlib
from _1_calculate_snow_droughts_mult_sources import FormatData,CalcSnowDroughts
from sklearn.preprocessing import MinMaxScaler


#suppress the SettingWithCopy warning in pandas 
pd.options.mode.chained_assignment = None  # default='warn'

def mann_whitney_u_test(distribution_1, distribution_2):
    """
    Perform the Mann-Whitney U Test, comparing two different distributions.
    Args:
       distribution_1: List. 
       distribution_2: List.
    Outputs:
        u_statistic: Float. U statisitic for the test.
        p_value: Float.
    """
    u_statistic, p_value = stats.mannwhitneyu(distribution_1, distribution_2)
    return u_statistic, p_value
		

def kruskall_wallis(df,cols): # list of the dfs you want to compare  
	"""Run Kruskal-Wallis H test. This is analogous to 1 way ANOVA but for non-parametric applications. 
	The conover test is used for post-hoc testing to determine relationship between variables. NOTE that the post hoc tests 
	should only be used when there is a significant result of the omnibus test.""" 

	#deal with cases where all vals in a col are nan 
	#input_df=input_df.dropna(axis=1, how='all')
	#set inf to nan 
	data = [df[col] for col in cols]
	# print(data)
	#input_df=input_df.replace(np.inf,np.nan)
	# Data = pandas.read_csv("CSVfile.csv")
	

	# print("Kruskal Wallis H-test test:")

	# H, pval = mstats.kruskalwallis(Col_1, Col_2, Col_3, Col_4)
	# if input_df.isnull().all().all():
	# 	return None
	# #reformat the df cols into arrays to pass to the stats func 
	# data = [input_df[column].to_numpy() for column in input_df.columns if not column=='huc8']
	
	#run the kruskal-wallis 
	try: 
		H,p = stats.kruskal(*data,nan_policy='omit') #*data

	except Exception as e: 
		print('broken')
	#return H,p
	#print(H,p)
	try: 
		#run the post-hoc test 
		#conover = sp.posthoc_conover([input_df.dropna().iloc[:,0].values,input_df.dropna().iloc[:,1].values,input_df.dropna().iloc[:,2].values,input_df.dropna().iloc[:,3].values],p_adjust='holm')
		conover = sp.posthoc_conover(data,p_adjust='holm')
		conover.columns = cols
		conover.index = cols
		
		return H,p,conover 
		
	except Exception as e: 
		print('Error is: ', e)


def condense_rs_data(input_df,date_col='date',sort_col='huc8',agg_col='NDSI_Snow_Cover',data_type='sca',resolution=500):

	#add a year col for the annual ones 
	input_df[date_col]= pd.to_datetime(input_df[date_col])

	input_df['year'] = input_df[date_col].dt.year

	if data_type.lower()=='sca': #this is already a sum of the SCA in a given basin so get max extent 
		#convert the SCA pixel count to area 
		input_df[agg_col] = (input_df[agg_col]*resolution*resolution)/1000000

		#get an aggregate statistic for each year, basin and season (season is determined by the df that is passed)
		output_df = input_df.groupby([sort_col,'year'])[agg_col].mean().reset_index()#.agg({self.swe_c:'max',self.precip:'sum'})
	
	elif data_type.lower()=='sp': 
		pass

	else: 
		print('Your data type for the RS data is neither sp nor sca. Double check what you are doing.')

	#get the long-term means 
	median = output_df.groupby(sort_col)['NDSI_Snow_Cover'].mean().reset_index()
	
	#rename the means cols so when they merge they have distinct names 
	median.rename(columns={'NDSI_Snow_Cover':'median'},inplace=True)

	median = dict(zip(median[sort_col],median['median']))

	#merge the means with the summary stats for each year/basin- this can be split for the three processing periods 
	#output_df = output_df.merge(median[[sort_col,'median']],how='inner',on=sort_col)
	output_df['median']=output_df[sort_col].map(median)

	#calculate the sca as a percent of the the long term median sca 
	output_df['adjusted']=output_df[agg_col]/output_df['median']

	#use feature scaling to rescale to -1 - 1
	scaler = MinMaxScaler()
	output_df['adjusted'] = scaler.fit_transform(output_df['adjusted'].values.reshape(-1,1))
	#output_df['adjusted'] = -1 + ((output_df.adjusted-output_df.adjusted.min())*(1-(-1)))/(output_df.adjusted.max()-output_df.adjusted.min())

	return output_df

def format_snotel_data(pickles,start_date='1980-10-01',end_date='2020-09-30',**kwargs): 
	"""Read in snotel data for climatological variables which has been acquired from the NRCS API and pickled to disk."""

	#read in some pickled objects, these look like a list of dfs with each being a station for the full time period 
	output=[]

	for item in ['PREC','TAVG','WTEQ']:
		#get the pickled objects for each parameter  
		files = glob.glob(pickles+f'*{item}_{start_date}_{end_date}_snotel_data_list') #hardcoded currently
		df=FormatData(files,drop_cols=['year','month','day']).read_in_pickles()
		output.append(df)
	
	#join the three enviro params 
	output_df = reduce(lambda left,right: pd.merge(left,right,how='inner',on=['date','id']), output)
	#print(output_df)
	
	#convert the temp column from F to C 
	output_df['TAVG'] = (output_df['TAVG']-32)*(5/9) 

	#convert prec and swe cols from inches to cm 
	output_df['PREC'] = output_df['PREC']*2.54
	output_df['WTEQ'] = output_df['WTEQ']*2.54
	
	#remove rows that have one of the data types missing- this might need to be amended because 
	#it means that there are different numbers of records in some of the periods. 
	output_df=output_df.dropna()
	
	#cast the snotel id col to int to add the hucs 
	output_df['id'] = output_df['id'].astype('int')

	#add the as yet nonexistant hucs data to the outputs 
	hucs = kwargs.get('hucs')
	output_df['huc8'] = output_df['id'].map(hucs)

	#there are multiple snotel stations in some of the basins, 
	#combine those so there is just one number per basin like the 
	#daymet and RS data. 
	return output_df.groupby(['huc8','date'])['PREC','WTEQ','TAVG'].mean().reset_index()

def add_drought_cols_to_df(df1,rs_df,sort_col='huc8',year_col='year'): 

	#merge the snotel or daymet with RS data 
	output_df = df1.merge(rs_df,on=[sort_col,year_col],how='inner')
	
	if 's_dry' in output_df.columns: 
		data_source = 's'
	elif 'd_dry' in output_df.columns: 
		data_source = 'd'
	else: 
		data_source = input('Put the first letter of the dataset you are using\nwhatever was used to create the snow drought data. ').lower() 
	#add the snow drought types as cols 
	try: 
		output_df['rs_dry'] = np.where(~output_df[data_source+'_dry'].isnull(),output_df['adjusted'],np.nan)
		output_df['rs_warm'] = np.where(~output_df[data_source+'_warm'].isnull(),output_df['adjusted'],np.nan)
		output_df['rs_warm_dry'] = np.where(~output_df[data_source+'_warm_dry'].isnull(),output_df['adjusted'],np.nan)
	except KeyError as e: 
		print('There was an issue getting the dry, warm or warm/dry cols. Please double check what those are called.')

	#get a new col that is the instances where there is no snow drought 
	output_df['no_drought'] = np.where((output_df['rs_dry'].isnull())&
		(output_df['rs_warm'].isnull())&
		(output_df['rs_warm_dry'].isnull()),
		output_df['adjusted'],np.nan)
		
	return output_df

def log_metadata(output_file,output_dict): 
	"""Create a metadata file about the run and write to disk."""

	# create list of strings from dictionary 
	list_of_strings = [ f'{key} : {output_dict[key]}' for key in output_dict ]

	# write string one by one adding newline
	with open(output_file, 'w') as file:
	    [ file.write(f'{st}\n') for st in list_of_strings ]
	return None

def main(sp_data,sca_data,pickles,season,index,data_type,output_dir,daymet_dir,agg_step=12,huc_level='8',resolution=500,**kwargs):
	"""
	Link the datatypes together and add summary stats. 
	"""
	# #read in some modis/viirs data
	# rs_early=condense_rs_data(FormatData(glob.glob(sca_data+'*_12_huc8_no_forest_thresh.csv'),drop_cols=['system:index','.geo']).read_in_csvs())
	# rs_mid=condense_rs_data(FormatData(glob.glob(sca_data+'*_2_huc8_no_forest_thresh.csv'),drop_cols=['system:index','.geo']).read_in_csvs())
	# rs_late=condense_rs_data(FormatData(glob.glob(sca_data+'*_4_huc8_no_forest_thresh.csv'),drop_cols=['system:index','.geo']).read_in_csvs())

	#read in the daymet data 
	early=FormatData(glob.glob(daymet_dir+'*_12_huc8.csv'),drop_cols=['system:index','.geo','dayl','vp']).read_in_csvs()
	mid=FormatData(glob.glob(daymet_dir+'*_2_huc8.csv'),drop_cols=['system:index','.geo','dayl','vp']).read_in_csvs()
	late=FormatData(glob.glob(daymet_dir+'*_4_huc8.csv'),drop_cols=['system:index','.geo','dayl','vp']).read_in_csvs()
	
	################################################################
	#next get the snotel data
	snotel_data=format_snotel_data(pickles,**kwargs)

	period_list = []
	snotel_periods=[]
	daymet_periods=[]
	for p1,p2 in zip(['early','mid','late'],[early,mid,late]): 
		print(f'Doing the {p1} period')
		#get snotel first
		#make a temporal chunk of data 
		snotel_chunk=FormatData(None,time_period=p1).split_yearly_data(snotel_data)
		
		#make a rs chunk of the data- will be one df with all years and the full winter 
		rs_chunk = FormatData(glob.glob(sca_data+'*.csv'),drop_cols=['system:index','.geo']).read_in_csvs()
		#split that df into the season to match other data 
		rs_chunk = condense_rs_data(FormatData(None,time_period=p1).split_yearly_data(rs_chunk))

		# print('chunk rs')
		# print(rs_chunk)

		#calculate the snow droughts for that chunk 
		if (p1 == 'mid') | (p1 == 'late'): 
			snotel_drought=CalcSnowDroughts(snotel_chunk,swe_c='WTEQ',precip='PREC',temp='TAVG',start_year=1991).calculate_snow_droughts()
			#print('snotel')
			#print(snotel_drought)
		else: 
			snotel_drought=CalcSnowDroughts(snotel_chunk,swe_c='WTEQ',precip='PREC',temp='TAVG').calculate_snow_droughts()
		
		#get cols of interest 
		snotel_drought=snotel_drought[['huc8','year','dry','warm','warm_dry']]
		#rename cols so they don't get confused when data are merged 
		snotel_drought.columns=['huc8','year']+['s_'+column for column in snotel_drought.columns if not (column =='huc8') | (column=='year')]
		
		#then do the same for daymet  
		if (p1 == 'mid') | (p1 == 'late'): 
			daymet_drought=CalcSnowDroughts(p2,start_year=1991).calculate_snow_droughts()
		else: 
			daymet_drought=CalcSnowDroughts(p2).calculate_snow_droughts()
		#print('daymet',daymet_drought)
		daymet_drought=daymet_drought[['huc8','year','dry','warm','warm_dry']]
		
		daymet_drought.columns=['huc8','year']+['d_'+column for column in daymet_drought.columns if not (column =='huc8') | (column=='year')]

		#join the snotel, daymet and rs data and add a few cols for plotting 
		snotel_drought=add_drought_cols_to_df(snotel_drought,rs_chunk)
		daymet_drought=add_drought_cols_to_df(daymet_drought,rs_chunk)
		#merge the two datasets into one df 
		#dfs = snotel_drought.merge(daymet_drought,on=['huc8','year'],how='inner')
		snotel_periods.append(snotel_drought)
		daymet_periods.append(daymet_drought)
	
		cols = ['rs_dry','rs_warm','rs_warm_dry','no_drought']
		print('counts')

		#save data to disk 
		print('mean')
		print(daymet_drought[cols].mean())
		print(snotel_drought[cols].mean())


		#run the stats
		daymet_kw = kruskall_wallis(daymet_drought,cols)
		snotel_kw = kruskall_wallis(snotel_drought,cols)

		print(daymet_kw)
		print(snotel_kw)

		print('testing')
		daymet_ls=daymet_drought[cols].values.T.ravel()
		daymet_ls = [x for x in daymet_ls if (math.isnan(x) == False)]

		snotel_ls=snotel_drought[cols].values.T.ravel()
		snotel_ls = [x for x in snotel_ls if (math.isnan(x) == False)]
		
		# daymet_mw = mann_whitney_u_test(daymet_ls,daymet_drought['no_drought'].dropna())
		# snotel_mw = mann_whitney_u_test(snotel_ls,snotel_drought['no_drought'].dropna())

		# print(daymet_mw)
		# print(snotel_mw)
		#daymet_mw = mann_whitney_u_test(daymet_drought[cols].melt())
	#plot the distribution of rs data for the three seasons and three drought types

	#cols=['dry','warm','warm_dry']
	xlabels=['Dry', 'Warm', 'Warm/dry']#, 'No drought']
	titles=['Early','Mid','Late']
	models=['Snotel','Daymet']
	nrow=2
	ncol=3
	fig,axs = plt.subplots(nrow,ncol,sharex=True,sharey=True,
				gridspec_kw={'wspace':0,'hspace':0,
                                    'top':0.95, 'bottom':0.05, 'left':0.05, 'right':0.95},
                figsize=(nrow*2,ncol*2))

	s_colors = ['#ccc596','#e4b047','#D95F0E','#666666']
	d_colors = ['#d4cfd9','#95aac5','#267eab','#666666']
	colors = list(kwargs.get('palette').values())
	for x in range(nrow): 
		for y in range(ncol): 
			#when y label is given xlabel is default, overwrite that
			
			if x == 0: 
				sns.boxplot(x="variable", y="value", data=pd.melt(snotel_periods[y][cols]),ax=axs[x][y],palette=s_colors)
				axs[x][y].set_title(titles[y],fontdict={'fontsize': 14})

			elif x > 0: 
				sns.boxplot(x="variable", y="value", data=pd.melt(daymet_periods[y][cols]),ax=axs[x][y],palette=d_colors)
				axs[x][y].set_xticklabels(xlabels,fontsize=12)
			axs[x][y].set_xlabel('')
			axs[x][y].set_ylabel('')
			axs[x][y].grid(axis='y',alpha=0.5)
		axs[x][0].set_ylabel(models[x],fontsize=14)	
		
	
	plt.show()
	plt.close('all')


if __name__ == '__main__':
	params = sys.argv[1]
	with open(str(params)) as f:
		variables = json.load(f)		
		#construct variables from param file
		sp_data = variables['sp_data']
		sca_data = variables['sca_data']
		pickles = variables['pickles']
		season = variables['season']
		palette = variables['palette'] #"no_drought":"#cbbdb1",
		hucs_data = variables['hucs_data']
		huc_shapefile = variables['huc_shapefile']
		stations=variables['stations']
		daymet_dir=variables['daymet_dir']

	hucs=pd.read_csv(stations)

	#get just the id cols 
	hucs = hucs[['huc_08','id']]
	
	#rename the huc col
	hucs.rename({'huc_08':'huc8'},axis=1,inplace=True)
	
	hucs_dict=dict(zip(hucs.id,hucs.huc8))
	
	#example function call for just optical data 
	#main(sp_data,sca_data,pickles,season,index=2,data_type='SAR',output_dir=pickles) #note that index can be 0-2 for SCA and only 0 for SP 

	#example call for SAR data included
	main(sp_data,sca_data,pickles,season,-9999,daymet_dir=daymet_dir,data_type='SCA',
	output_dir=pickles,hucs_data=hucs_data,huc_shapefile=huc_shapefile,hucs=hucs_dict,palette=palette)#,sar_data=sentinel_csv_dir) #note that index can be 0-2 for SCA and only 0 for SP 

	#calculate stats 
	# print(snotel_drought.dtypes)
	# stats_out = {}
	# for huc in set(snotel_drought['huc8']): 
	# 	#print(huc)
	# 	stats_input = snotel_drought.loc[snotel_drought['huc8']==int(huc)]#[df.loc[df['huc8']==int(huc)] for df in sca_dfs]
	# 	print(stats_input)
	# 	stats_out.update({huc:run_stats(stats_input,cols)})

	# print(stats_out)

	# hucs_gdf = gpd.read_file(kwargs.get('huc_shapefile'))
	
	# #print(hucs_gdf.columns)
	# dry_warm = {}
	# dry_warm_dry = {}
	# dry_total = {}
	# warm_warm_dry= {}
	# warm_total={}
	# warm_dry_total={}
	# count = 0
	# for k,v in stats_out.items(): 
	# 	try: 

	# 		# print(v[2].iat[1,0])
	# 		# print(v[2])
	# 		dry_warm.update({k:v[2].iat[1,0]})
	# 		dry_warm_dry.update({k:v[2].iat[2,0]})		
	# 		dry_total.update({k:v[2].iat[3,0]})
	# 		warm_warm_dry.update({k:v[2].iat[2,1]})
	# 		warm_total.update({k:v[2].iat[1,3]})
	# 		warm_dry_total.update({k:v[2].iat[3,2]})

	# 	except Exception as e: 
	# 		print(f'error here was: {e}')
	# 		print(v)
	# 		count +=1 
	# #print(dry_warm)
	# print(f'there were {count} errors in this run ')
	# hucs_gdf['huc8'] = hucs_gdf['huc8'].astype('int')
	
	# hucs_gdf['dry_warm'] = ((hucs_gdf['huc8'].map(dry_warm)) <=0.05).astype('int')
	# hucs_gdf['dry_warm_dry'] = ((hucs_gdf['huc8'].map(dry_warm_dry)) <= 0.05).astype('int')
	# hucs_gdf['dry_total'] = ((hucs_gdf['huc8'].map(dry_total)) <=0.05).astype('int')
	# hucs_gdf['warm_warm_dry'] = ((hucs_gdf['huc8'].map(warm_warm_dry)) <=0.05).astype('int')
	# hucs_gdf['warm_total'] = ((hucs_gdf['huc8'].map(warm_warm_dry)) <=0.05).astype('int')
	# hucs_gdf['warm_dry_total'] = ((hucs_gdf['huc8'].map(warm_dry_total)) <=0.05).astype('int')

	# # print('df looks like')
	# # print(hucs_gdf)
	
	# # hucs_gdf.loc[hucs_gdf['dry_warm'] <=0.05] =1#hucs_gdf['dry_warm'] 
	# # hucs_gdf.loc[hucs_gdf['dry_warm_dry'] <=0.05]=1#hucs_gdf['dry_warm_dry']
	# # hucs_gdf.loc[hucs_gdf['dry_total'] <=0.05]=1#hucs_gdf['dry_total'] 
	# # hucs_gdf.loc[hucs_gdf['warm_warm_dry'] <=0.05]=1#hucs_gdf['warm_warm_dry'] 
	# # hucs_gdf.loc[hucs_gdf['warm_total'] <=0.05]=1#hucs_gdf['warm_total'] 
	# # hucs_gdf.loc[hucs_gdf['warm_dry_total'] <=0.05]=1#hucs_gdf['warm_dry_total'] 

	# #data_df["mean_radius"] = (data_df["mean radius"] <= 12.0).astype(int)
	# #data_df.loc[data_df["mean radius"] > 12.0, "mean radius"] = 0


	# print(hucs_gdf)
	# plot_cols = ['dry_warm','dry_warm_dry','dry_total','warm_warm_dry','warm_total','warm_dry_total']
	# fig,ax = plt.subplots(3,2,sharex=True,sharey=True,figsize=(12,10))	
	# cmap=matplotlib.colors.ListedColormap(['#7f7f7f','#CC7000'])

	# ax = ax.flatten()
	# for i in range(6): 
	# 	hucs_gdf.plot(column=plot_cols[i],ax=ax[i], 
	# 	cmap=cmap,legend=True,#,#,missing_kwds={
	# 	# 		"color": "lightgrey",
	# 	# 		"edgecolor": "red",
	# 	# 		"hatch": "///",
	# 	# 		"label": "Missing values"}, 
	# 	legend_kwds={'label': "Kruskal-Wallis test (alpha 0.05)",
	# 	'orientation': "horizontal"})#,color={'#000000':0,'#ff0000':1})
	# 	#ax[i].legend()
	# 	ax[i].set_title(plot_cols[i])
	# # handles, labels = ax[5].get_legend_handles_labels()
	# # fig.legend(handles, labels, loc='center')
	# plt.tight_layout()
	# plt.show()
	# plt.close('all')